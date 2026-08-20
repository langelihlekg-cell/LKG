"""
Depth-based parametric parallax renderer.

Core idea: sample one full camera-motion period over exactly N frames
(phase_i = 2*pi*i/N). This guarantees two things Apple's QC cares about
for free, by construction rather than by post-hoc correction:
  - frame 0 has phase 0 -> zero offset, zero zoom delta -> pixel-identical
    to a static render of the source (satisfies "first frame = static cover").
  - the wrap from the last frame back to frame 0 is the same size step as
    every other consecutive-frame step -> seamless loop, no jump cut.

Nearer regions (per the depth map) are displaced more than far regions as
the virtual camera pans/zooms -> parallax. This is a classic 2.5D technique,
not a neural video model, which is exactly why it's cheap and controllable.
"""
from __future__ import annotations
import os
import subprocess
import shutil
import numpy as np
import cv2

# Real Apple deliverable dimensions (see the motion-artwork-api-spec.md contract)
PRODUCTION_SQUARE = (3840, 3840)      # 1:1, iPad/Mac/TV
PRODUCTION_VERTICAL = (2048, 2732)    # 3:4, iPhone/Android full-bleed player

# Scaled-down dims used only for fast sandbox/CI testing of the pipeline logic.
# Same code path, just smaller — swap in PRODUCTION_* for real delivery.
DEMO_SQUARE = (480, 480)
DEMO_VERTICAL = (480, 640)


def compose_vertical_canvas(square_rgb: np.ndarray, target_w: int, target_h: int) -> np.ndarray:
    """
    Builds the 3:4 canvas from the square source: a heavily blurred, darkened
    cover-crop background fills the frame, with the sharp square composited
    centered on top. This is a defensible design choice, not an Apple-verified
    spec — cross-check against Apple's official After Effects safe-area
    template before final delivery (see README).
    """
    sq_h, sq_w = square_rgb.shape[:2]

    # Background: cover-crop + blur + darken
    scale = max(target_w / sq_w, target_h / sq_h)
    bg = cv2.resize(square_rgb, (int(sq_w * scale) + 1, int(sq_h * scale) + 1))
    by, bx = bg.shape[0], bg.shape[1]
    top = (by - target_h) // 2
    left = (bx - target_w) // 2
    bg = bg[top:top + target_h, left:left + target_w]
    bg = cv2.GaussianBlur(bg, (0, 0), sigmaX=target_w * 0.03)
    bg = (bg.astype(np.float32) * 0.55).astype(np.uint8)

    # Foreground: square scaled to fit width, centered vertically
    fg_w = target_w
    fg_h = int(sq_h * (fg_w / sq_w))
    fg = cv2.resize(square_rgb, (fg_w, fg_h))
    canvas = bg.copy()
    y0 = (target_h - fg_h) // 2
    if y0 >= 0:
        canvas[y0:y0 + fg_h, 0:fg_w] = fg
    else:
        crop_top = -y0
        canvas[0:target_h, 0:fg_w] = fg[crop_top:crop_top + target_h, :]
    return canvas


def render_frame(source_rgb: np.ndarray, depth: np.ndarray, phase: float,
                  parallax_gain: float, zoom_gain: float) -> np.ndarray:
    """One frame at a given phase (radians, 0..2*pi). phase=0 -> identity."""
    h, w = source_rgb.shape[:2]
    cy, cx = h / 2.0, w / 2.0

    offset_x = parallax_gain * w * np.sin(phase)
    offset_y = parallax_gain * h * 0.35 * np.sin(phase + np.pi / 2)  # gentle secondary drift
    zoom = 1.0 + zoom_gain * (1 - np.cos(phase)) / 2.0  # 1.0 at phase=0

    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    # zoom about center
    map_x = cx + (xx - cx) / zoom
    map_y = cy + (yy - cy) / zoom
    # depth-weighted parallax: closer (depth->1) moves more than far (depth->0)
    map_x = map_x + offset_x * depth
    map_y = map_y + offset_y * depth

    return cv2.remap(
        source_rgb, map_x.astype(np.float32), map_y.astype(np.float32),
        interpolation=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT101,
    )


def render_frame_sequence(source_rgb: np.ndarray, depth: np.ndarray, n_frames: int,
                           parallax_gain: float = 0.018, zoom_gain: float = 0.045):
    for i in range(n_frames):
        phase = 2 * np.pi * i / n_frames
        yield render_frame(source_rgb, depth, phase, parallax_gain, zoom_gain)


def encode_frames_to_video(frame_paths_dir: str, fps: int, n_frames: int, out_path: str,
                            codec: str = "h264", bitrate_mbps: float = 8.0) -> None:
    """No -i audio input at all -> zero audio streams, satisfying Apple's
    'no audio track' rule by construction rather than by stripping later."""
    if codec == "h264":
        cmd = [
            "ffmpeg", "-y", "-framerate", str(fps),
            "-i", os.path.join(frame_paths_dir, "%06d.png"),
            "-frames:v", str(n_frames), "-an",
            "-c:v", "libx264", "-preset", "medium", "-pix_fmt", "yuv420p",
            # True x264 CBR requires minrate == maxrate == bitrate EXACTLY —
            # confirmed by testing: a +/-10-15% band silently fails with
            # "CBR HRD requires constant bitrate" logged by libx264, which then
            # falls back to VBR HRD and lets low-motion/low-entropy content
            # (smooth gradients, static backgrounds) undershoot the target by
            # 8-10x on ABR's default rate control. Exact equality is required,
            # not a tolerance range.
            "-b:v", f"{bitrate_mbps}M", "-minrate", f"{bitrate_mbps}M",
            "-maxrate", f"{bitrate_mbps}M", "-bufsize", f"{bitrate_mbps * 0.5}M",
            "-x264-params", "nal-hrd=cbr:force-cfr=1",
            out_path,
        ]
    elif codec == "prores":
        cmd = [
            "ffmpeg", "-y", "-framerate", str(fps),
            "-i", os.path.join(frame_paths_dir, "%06d.png"),
            "-frames:v", str(n_frames), "-an",
            "-c:v", "prores_ks", "-profile:v", "3", "-pix_fmt", "yuv422p10le",
            "-vendor", "apl0", "-qscale:v", "9",
            out_path,
        ]
    else:
        raise ValueError(f"unknown codec {codec}")

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed:\n{result.stderr[-2000:]}")


def render_deliverable(source_rgb: np.ndarray, depth_estimator, target_w: int, target_h: int,
                        duration_s: float, fps: int, out_path: str, codec: str,
                        bitrate_mbps: float, is_vertical: bool, tmp_dir: str) -> str:
    if is_vertical:
        canvas = compose_vertical_canvas(source_rgb, target_w, target_h)
    else:
        canvas = cv2.resize(source_rgb, (target_w, target_h))

    depth = depth_estimator.estimate(canvas)
    n_frames = int(round(duration_s * fps))

    frame_dir = os.path.join(tmp_dir, "frames_" + ("v" if is_vertical else "s"))
    os.makedirs(frame_dir, exist_ok=True)
    for i, frame in enumerate(render_frame_sequence(canvas, depth, n_frames)):
        cv2.imwrite(os.path.join(frame_dir, f"{i:06d}.png"),
                    cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))

    encode_frames_to_video(frame_dir, fps, n_frames, out_path, codec, bitrate_mbps)
    shutil.rmtree(frame_dir, ignore_errors=True)
    return out_path


def render_pair(source_image_path: str, out_dir: str, depth_estimator,
                 duration_s: float = 12.0, fps: int = 24, codec: str = "h264",
                 bitrate_mbps: float = 8.0, dims=(PRODUCTION_SQUARE, PRODUCTION_VERTICAL)) -> dict:
    """Renders BOTH deliverables from the same source, guaranteeing identical
    duration/fps (Apple requires the two files to match exactly)."""
    os.makedirs(out_dir, exist_ok=True)
    tmp_dir = os.path.join(out_dir, "_tmp")
    os.makedirs(tmp_dir, exist_ok=True)

    src = cv2.imread(source_image_path)
    src = cv2.cvtColor(src, cv2.COLOR_BGR2RGB)

    square_dims, vertical_dims = dims
    # .mp4 for H.264 (plays inline in every browser via <video>, no download
    # prompt) — Apple's spec allows H.264 in either .mp4 or .mov, so this is
    # still compliant. ProRes needs the .mov container regardless.
    ext = "mov" if codec == "prores" else "mp4"
    square_path = os.path.join(out_dir, f"square_1x1.{ext}")
    vertical_path = os.path.join(out_dir, f"vertical_3x4.{ext}")

    render_deliverable(src, depth_estimator, *square_dims, duration_s, fps,
                        square_path, codec, bitrate_mbps, is_vertical=False, tmp_dir=tmp_dir)
    render_deliverable(src, depth_estimator, *vertical_dims, duration_s, fps,
                        vertical_path, codec, bitrate_mbps, is_vertical=True, tmp_dir=tmp_dir)

    shutil.rmtree(tmp_dir, ignore_errors=True)
    return {"square_1x1": square_path, "vertical_3x4": vertical_path}
