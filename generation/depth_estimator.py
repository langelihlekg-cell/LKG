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
      1. Spectral-residual saliency (Hou & Zhang, 2007, via cv2.saliency) —
         a real, published foreground-detection algorithm, not a made-up heuristic.
      2. A mild center-weighted prior, since cover art conventionally frames
         the subject centrally.
      3. Local contrast (Laplacian energy) as a secondary "in-focus = close" cue.
    Blended and smoothed into a single depth proxy.
    """

    def __init__(self, saliency_weight=0.55, center_weight=0.20, contrast_weight=0.25):
        self.saliency_weight = saliency_weight
        self.center_weight = center_weight
        self.contrast_weight = contrast_weight
        self._saliency = cv2.saliency.StaticSaliencySpectralResidual_create()

    def estimate(self, image_rgb: np.ndarray) -> np.ndarray:
        h, w = image_rgb.shape[:2]
        bgr = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2BGR)

        # 1. Saliency map
        success, sal = self._saliency.computeSaliency(bgr)
        if not success:
            sal = np.ones((h, w), dtype=np.float32) * 0.5
        sal = sal.astype(np.float32)
        sal = (sal - sal.min()) / (sal.max() - sal.min() + 1e-8)

        # 2. Center-weighted prior
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        cy, cx = h / 2.0, w / 2.0
        dist = np.sqrt(((yy - cy) / (h / 2)) ** 2 + ((xx - cx) / (w / 2)) ** 2)
        center_prior = np.clip(1.0 - dist, 0, 1)

        # 3. Local contrast via Laplacian energy in a small window
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
        lap = cv2.Laplacian(gray, cv2.CV_32F, ksize=3)
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
