"""
Depth estimation for the motion-artwork pipeline.

Design: one interface, two implementations.
  - ClassicalDepthEstimator: CPU-only, no ML weights, runs anywhere. This is
    what's used in this repo's tests because the build/dev sandbox has no GPU
    and no network access to download model weights.
  - DepthAnythingV2Estimator: the real production model. Same interface, so
    swapping it in is a one-line change in render.py — nothing else in the
    pipeline needs to know which one is running.

Do not ship ClassicalDepthEstimator to production. It's a structurally
reasonable stand-in (saliency + center prior), not a monocular depth model,
and will produce flatter, less convincing parallax than a real model.
"""
from __future__ import annotations
import numpy as np
import cv2


class DepthEstimator:
    def estimate(self, image_rgb: np.ndarray) -> np.ndarray:
        """
        image_rgb: (H, W, 3) uint8
        Returns: (H, W) float32 depth map normalized to [0, 1],
                 where 1.0 = closest to camera (moves most), 0.0 = farthest.
        """
        raise NotImplementedError


class ClassicalDepthEstimator(DepthEstimator):
    """
    CPU stand-in using:
      1. Spectral-residual saliency (Hou & Zhang, 2007) — implemented directly
         with numpy's FFT below, NOT via cv2.saliency. That module only ships
         in opencv-contrib-python(-headless), not the plain opencv-python-
         headless this repo's requirements install — a real packaging gap
         that only worked in the original build sandbox because a contrib
         build happened to already be present there, which is exactly the
         "works on my machine" failure mode this rewrite removes. Same
         published algorithm, zero non-standard dependency.
      2. A mild center-weighted prior, since cover art conventionally frames
         the subject centrally.
      3. Local contrast (Laplacian energy) as a secondary "in-focus = close" cue.
    Blended and smoothed into a single depth proxy.
    """

    def __init__(self, saliency_weight=0.55, center_weight=0.20, contrast_weight=0.25):
        self.saliency_weight = saliency_weight
        self.center_weight = center_weight
        self.contrast_weight = contrast_weight

    @staticmethod
    def _spectral_residual_saliency(gray: np.ndarray, work_size: int = 64) -> np.ndarray:
        """Hou & Zhang 2007, from scratch: FFT -> log amplitude -> subtract a
        locally-smoothed version of itself (the 'residual') -> reconstruct
        with the original phase -> square -> smooth. Downscaling to a small
        fixed size first is standard for this algorithm (cheaper, and the
        method is intentionally low-resolution/coarse by design)."""
        h, w = gray.shape
        small = cv2.resize(gray, (work_size, work_size), interpolation=cv2.INTER_AREA).astype(np.float64)

        f = np.fft.fft2(small)
        amplitude = np.abs(f)
        phase = np.angle(f)
        log_amp = np.log(amplitude + 1e-8)
        avg_log_amp = cv2.blur(log_amp, (3, 3))
        residual = log_amp - avg_log_amp

        reconstructed = np.fft.ifft2(np.exp(residual + 1j * phase))
        sal_small = np.abs(reconstructed) ** 2
        sal_small = cv2.GaussianBlur(sal_small.astype(np.float32), (0, 0), sigmaX=2.0)

        sal = cv2.resize(sal_small, (w, h), interpolation=cv2.INTER_LINEAR)
        sal = (sal - sal.min()) / (sal.max() - sal.min() + 1e-8)
        return sal.astype(np.float32)

    def estimate(self, image_rgb: np.ndarray) -> np.ndarray:
        h, w = image_rgb.shape[:2]
        bgr = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2BGR)
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

        # 1. Saliency map
        sal = self._spectral_residual_saliency(gray)

        # 2. Center-weighted prior
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        cy, cx = h / 2.0, w / 2.0
        dist = np.sqrt(((yy - cy) / (h / 2)) ** 2 + ((xx - cx) / (w / 2)) ** 2)
        center_prior = np.clip(1.0 - dist, 0, 1)

        # 3. Local contrast via Laplacian energy in a small window
        gray_f = gray.astype(np.float32)
        lap = cv2.Laplacian(gray_f, cv2.CV_32F, ksize=3)
        lap_energy = cv2.GaussianBlur(np.abs(lap), (0, 0), sigmaX=max(w, h) * 0.01)
        lap_energy = (lap_energy - lap_energy.min()) / (lap_energy.max() - lap_energy.min() + 1e-8)

        depth = (
            self.saliency_weight * sal
            + self.center_weight * center_prior
            + self.contrast_weight * lap_energy
        )

        # Smooth so parallax warps as coherent regions, not per-pixel noise
        depth = cv2.GaussianBlur(depth, (0, 0), sigmaX=max(w, h) * 0.006)
        depth = (depth - depth.min()) / (depth.max() - depth.min() + 1e-8)
        return depth.astype(np.float32)


class DepthAnythingV2Estimator(DepthEstimator):
    """
    Production implementation. Requires (not installed in this sandbox —
    no network to fetch weights, no GPU):
        pip install torch transformers pillow
    Swap into render.py via ESTIMATOR = DepthAnythingV2Estimator() once
    the worker container has GPU + model weights available (see
    generation/Dockerfile).
    """

    def __init__(self, model_name: str = "depth-anything/Depth-Anything-V2-Small-hf"):
        from transformers import pipeline  # deferred import: optional heavy dep
        self.pipe = pipeline(task="depth-estimation", model=model_name)

    def estimate(self, image_rgb: np.ndarray) -> np.ndarray:
        from PIL import Image
        pil_img = Image.fromarray(image_rgb)
        result = self.pipe(pil_img)
        depth = np.array(result["depth"], dtype=np.float32)
        depth = (depth - depth.min()) / (depth.max() - depth.min() + 1e-8)
        return depth
