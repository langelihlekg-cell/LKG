"""
Automated compliance suite for motion artwork deliverables.

This is the standalone product referenced in Phase 4 ("Trojan Horse" QC-only
endpoint) — it must work on ANY .mov/.mp4, not just files this system rendered,
because distributors will point it at freelancer- and competitor-made files too.

Numeric thresholds below (resolution, bitrate range, duration bounds, codecs,
frame rates) were checked against Apple's live Album Motion Guidelines page
(help.apple.com/itc/albummotionguide) as of 2026-09-03 and match exactly.
Re-verify before this gates real submissions if much time has passed — treat
CONFIG below as the single place to update them.

Three checks now cover spec requirements that nothing here validated before:
frame rate (Apple allows exactly 23.976/24/25/29.97/30 fps), pixel aspect
ratio (Apple requires square pixels, PAR 1:1), and color profile (Rec 709 or
sRGB). Frame rate and PAR are hard, reliable checks. Color profile is
deliberately soft — see check_color_profile's docstring for why an unset tag
has to pass rather than fail.
"""
from __future__ import annotations
import json
import subprocess
import numpy as np
import cv2
from scipy.ndimage import gaussian_filter

CONFIG = {
    "square_resolution": (3840, 3840),
    "vertical_resolution": (2048, 2732),
    "bitrate_range_mbps": (45, 100),
    "duration_range_s": (8, 35),
    "duration_match_tolerance_s": 0.05,
    "allowed_codecs": {"prores", "h264"},
    "allowed_frame_rates": {23.976, 24.0, 25.0, 29.97, 30.0},  # Apple's exact list
    "frame_rate_tolerance": 0.01,
    "pixel_aspect_ratio_tolerance": 0.01,
    "first_frame_similarity_min": 0.90,
    "loop_jump_ratio_max": 2.0,       # wrap step vs typical step
    "flash_luma_delta_sigma": 3.0,    # flag frame-to-frame jumps > N std devs
    "solid_frame_std_min": 3.0,       # below this pixel std = "solid color"
    "safe_area_margin_frac": 0.03,
    "safe_area_edge_energy_max": 0.35,  # fraction of total edge energy allowed in margin
}


def ffprobe_json(path: str) -> dict:
    cmd = ["ffprobe", "-v", "error", "-print_format", "json",
           "-show_format", "-show_streams", path]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed on {path}: {result.stderr}")
    return json.loads(result.stdout)


def _video_stream(probe: dict) -> dict:
    for s in probe["streams"]:
        if s["codec_type"] == "video":
            return s
    raise ValueError("no video stream found")


def check_resolution(probe: dict, expected_w: int, expected_h: int) -> dict:
    v = _video_stream(probe)
    ok = int(v["width"]) == expected_w and int(v["height"]) == expected_h
    return {"pass": ok, "found": f"{v['width']}x{v['height']}", "expected": f"{expected_w}x{expected_h}"}


def check_duration_range(probe: dict, min_s: float, max_s: float) -> dict:
    dur = float(probe["format"]["duration"])
    ok = min_s <= dur <= max_s
    return {"pass": ok, "found_seconds": round(dur, 3), "expected_range": [min_s, max_s]}


def check_duration_match(probe_a: dict, probe_b: dict, tolerance_s: float) -> dict:
    dur_a = float(probe_a["format"]["duration"])
    dur_b = float(probe_b["format"]["duration"])
    ok = abs(dur_a - dur_b) <= tolerance_s
    return {"pass": ok, "square_seconds": round(dur_a, 3), "vertical_seconds": round(dur_b, 3)}


def check_no_audio(probe: dict) -> dict:
    has_audio = any(s["codec_type"] == "audio" for s in probe["streams"])
    return {"pass": not has_audio, "audio_streams_found": sum(1 for s in probe["streams"] if s["codec_type"] == "audio")}


def check_bitrate_range(probe: dict, min_mbps: float, max_mbps: float) -> dict:
    bitrate_mbps = float(probe["format"]["bit_rate"]) / 1_000_000
    ok = min_mbps <= bitrate_mbps <= max_mbps
    return {"pass": ok, "found_mbps": round(bitrate_mbps, 2), "expected_range_mbps": [min_mbps, max_mbps]}


def check_codec(probe: dict, allowed: set) -> dict:
    v = _video_stream(probe)
    name = v["codec_name"]
    normalized = "prores" if "prores" in name else ("h264" if name == "h264" else name)
    return {"pass": normalized in allowed, "found": name}


def check_frame_rate(probe: dict, allowed: set, tolerance: float) -> dict:
    """Apple allows exactly 23.976, 24, 25, 29.97, or 30 fps — nothing else.
    A frame rate the renderer never intended (e.g. a demo-scale shortcut,
    or a third-party file this endpoint is checking) should fail loudly
    here rather than pass silently through the other checks."""
    v = _video_stream(probe)
    fps_num, fps_den = v["r_frame_rate"].split("/")
    fps = float(fps_num) / float(fps_den) if float(fps_den) != 0 else 0.0
    ok = any(abs(fps - allowed_fps) <= tolerance for allowed_fps in allowed)
    return {"pass": ok, "found_fps": round(fps, 3), "allowed_fps": sorted(allowed)}


def check_pixel_aspect_ratio(probe: dict, tolerance: float) -> dict:
    """Apple requires square pixels (PAR 1:1). Non-square PAR is rare in
    files this renderer produces, but a real risk in third-party files
    (e.g. anamorphic sources) run through the standalone QC endpoint —
    it distorts the image on playback without an obvious visual cue."""
    v = _video_stream(probe)
    sar = v.get("sample_aspect_ratio", "1:1")
    if sar in ("1:1", "N/A", None, ""):
        return {"pass": True, "found_sar": sar or "1:1", "ratio": 1.0}
    num, den = sar.split(":")
    ratio = float(num) / float(den) if float(den) != 0 else 1.0
    ok = abs(ratio - 1.0) <= tolerance
    return {"pass": ok, "found_sar": sar, "ratio": round(ratio, 4)}


def check_color_profile(probe: dict) -> dict:
    """Apple requires Rec 709 or sRGB. Deliberately a soft check: sRGB and
    Rec 709 share the same primaries, and ordinary H.264/ProRes exports very
    often leave color_primaries/color_space entirely unset in ffprobe --
    that's normal, not a violation, and there's no way to infer the real
    profile from an absent tag. So this only fails when the metadata
    explicitly names something incompatible (HDR spaces like bt2020 or PQ/
    HLG transfer curves); unset/unknown passes, with a note explaining why,
    rather than blocking a probably-fine file on missing metadata."""
    v = _video_stream(probe)
    primaries = v.get("color_primaries", "unknown")
    space = v.get("color_space", "unknown")
    transfer = v.get("color_transfer", "unknown")
    incompatible = {"bt2020", "bt2020nc", "bt2020c", "smpte2084", "arib-std-b67"}
    found = {primaries, space, transfer}
    ok = not (found & incompatible)
    result = {"pass": ok, "color_primaries": primaries, "color_space": space, "color_transfer": transfer}
    if primaries == "unknown" and space == "unknown" and transfer == "unknown":
        result["note"] = "no color metadata present in file -- treated as pass, cannot be inferred from absence"
    return result


def extract_frame(video_path: str, frame_index: int) -> np.ndarray:
    cmd = ["ffmpeg", "-y", "-i", video_path, "-vf", f"select=eq(n\\,{frame_index})",
           "-vframes", "1", "-f", "image2pipe", "-vcodec", "png", "pipe:1"]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0 or not result.stdout:
        raise RuntimeError(f"could not extract frame {frame_index} from {video_path}")
    arr = np.frombuffer(result.stdout, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)


def get_frame_count(probe: dict) -> int:
    v = _video_stream(probe)
    if "nb_frames" in v and v["nb_frames"] not in (None, "N/A"):
        return int(v["nb_frames"])
    dur = float(probe["format"]["duration"])
    fps_num, fps_den = v["r_frame_rate"].split("/")
    fps = float(fps_num) / float(fps_den)
    return int(round(dur * fps))


def _ssim(a: np.ndarray, b: np.ndarray) -> float:
    """Hand-rolled single-scale SSIM (Wang et al. 2004) on luma, since
    scikit-image isn't part of this environment's installed deps."""
    a = cv2.cvtColor(a, cv2.COLOR_RGB2GRAY).astype(np.float64)
    b = cv2.cvtColor(b, cv2.COLOR_RGB2GRAY).astype(np.float64)
    if a.shape != b.shape:
        b = cv2.resize(b, (a.shape[1], a.shape[0]))
    C1, C2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    sigma = 1.5
    mu_a, mu_b = gaussian_filter(a, sigma), gaussian_filter(b, sigma)
    mu_a2, mu_b2, mu_ab = mu_a * mu_a, mu_b * mu_b, mu_a * mu_b
    var_a = gaussian_filter(a * a, sigma) - mu_a2
    var_b = gaussian_filter(b * b, sigma) - mu_b2
    cov_ab = gaussian_filter(a * b, sigma) - mu_ab
    ssim_map = ((2 * mu_ab + C1) * (2 * cov_ab + C2)) / ((mu_a2 + mu_b2 + C1) * (var_a + var_b + C2))
    return float(ssim_map.mean())


def check_first_frame_matches_source(video_path: str, reference_rgb: np.ndarray, threshold: float) -> dict:
    frame0 = extract_frame(video_path, 0)
    score = _ssim(frame0, reference_rgb)
    return {"pass": score >= threshold, "similarity": round(score, 4), "threshold": threshold}


def check_seamless_loop(video_path: str, probe: dict, jump_ratio_max: float) -> dict:
    """
    Correct definition of 'seamless': the pixel-step from the last frame back
    to frame 0 should be roughly the SAME SIZE as a typical step between any
    other two consecutive frames — not that first and last frames are
    identical (they shouldn't be; that would mean the motion froze).
    """
    n = get_frame_count(probe)
    sample_indices = sorted(set(np.linspace(0, n - 1, min(8, n), dtype=int)))
    frames = [extract_frame(video_path, i) for i in sample_indices]

    steps = [np.abs(frames[i + 1].astype(np.float32) - frames[i].astype(np.float32)).mean()
             for i in range(len(frames) - 1)]
    typical_step = float(np.median(steps)) if steps else 0.0

    last_frame = extract_frame(video_path, n - 1)
    first_frame = frames[0]
    wrap_step = float(np.abs(last_frame.astype(np.float32) - first_frame.astype(np.float32)).mean())

    ratio = wrap_step / typical_step if typical_step > 1e-6 else 0.0
    ok = ratio <= jump_ratio_max
    return {"pass": ok, "wrap_step": round(wrap_step, 3), "typical_step": round(typical_step, 3),
            "ratio": round(ratio, 2), "max_allowed_ratio": jump_ratio_max}


def check_no_flash_or_solid_frames(video_path: str, probe: dict, cfg: dict) -> dict:
    n = get_frame_count(probe)
    sample_indices = sorted(set(np.linspace(0, n - 1, min(12, n), dtype=int)))
    frames = [extract_frame(video_path, i) for i in sample_indices]

    stds = [float(f.astype(np.float32).std()) for f in frames]
    solid_frames = [i for i, s in zip(sample_indices, stds) if s < cfg["solid_frame_std_min"]]

    lumas = [float(cv2.cvtColor(f, cv2.COLOR_RGB2GRAY).mean()) for f in frames]
    deltas = np.abs(np.diff(lumas))
    delta_std = deltas.std() if len(deltas) > 1 else 0.0
    delta_mean = deltas.mean() if len(deltas) else 0.0
    flash_frames = [sample_indices[i + 1] for i, d in enumerate(deltas)
                     if delta_std > 1e-6 and (d - delta_mean) / delta_std > cfg["flash_luma_delta_sigma"]]

    ok = not solid_frames and not flash_frames
    return {"pass": ok, "solid_color_frames": solid_frames, "flash_frames": flash_frames}


def check_safe_area(video_path: str, cfg: dict) -> dict:
    """Heuristic only: flags when a disproportionate share of high-frequency
    (edge) energy sits in the outer margin, i.e. content likely to be clipped
    by player UI chrome. Not a substitute for Apple's official safe-area
    template — treat a 'pass' here as a first-pass filter, not a guarantee."""
    frame = extract_frame(video_path, 0)
    gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY).astype(np.float32)
    edges = np.abs(cv2.Laplacian(gray, cv2.CV_32F))
    h, w = edges.shape
    m = int(min(h, w) * cfg["safe_area_margin_frac"])
    total_energy = edges.sum() + 1e-6
    margin_energy = edges[:m, :].sum() + edges[-m:, :].sum() + edges[:, :m].sum() + edges[:, -m:].sum()
    frac = float(margin_energy / total_energy)
    ok = frac <= cfg["safe_area_edge_energy_max"]
    return {"pass": ok, "margin_energy_fraction": round(frac, 3), "max_allowed": cfg["safe_area_edge_energy_max"]}


def run_qc_suite(square_path: str, vertical_path: str, source_image_path: str,
                  config: dict = CONFIG) -> dict:
    src = cv2.imread(source_image_path)
    src = cv2.cvtColor(src, cv2.COLOR_BGR2RGB)

    probe_sq = ffprobe_json(square_path)
    probe_v = ffprobe_json(vertical_path)

    checks = {
        "duration_match": check_duration_match(probe_sq, probe_v, config["duration_match_tolerance_s"]),
        "duration_range": check_duration_range(probe_sq, *config["duration_range_s"]),
        "resolution_1x1": check_resolution(probe_sq, *config["square_resolution"]),
        "resolution_3x4": check_resolution(probe_v, *config["vertical_resolution"]),
        "bitrate_range_square": check_bitrate_range(probe_sq, *config["bitrate_range_mbps"]),
        "bitrate_range_vertical": check_bitrate_range(probe_v, *config["bitrate_range_mbps"]),
        "codec_square": check_codec(probe_sq, config["allowed_codecs"]),
        "codec_vertical": check_codec(probe_v, config["allowed_codecs"]),
        "frame_rate_square": check_frame_rate(probe_sq, config["allowed_frame_rates"], config["frame_rate_tolerance"]),
        "frame_rate_vertical": check_frame_rate(probe_v, config["allowed_frame_rates"], config["frame_rate_tolerance"]),
        "pixel_aspect_ratio_square": check_pixel_aspect_ratio(probe_sq, config["pixel_aspect_ratio_tolerance"]),
        "pixel_aspect_ratio_vertical": check_pixel_aspect_ratio(probe_v, config["pixel_aspect_ratio_tolerance"]),
        "color_profile_square": check_color_profile(probe_sq),
        "color_profile_vertical": check_color_profile(probe_v),
        "audio_track_absent_square": check_no_audio(probe_sq),
        "audio_track_absent_vertical": check_no_audio(probe_v),
        "first_frame_matches_cover": check_first_frame_matches_source(
            square_path, src, config["first_frame_similarity_min"]),
        "seamless_loop_square": check_seamless_loop(square_path, probe_sq, config["loop_jump_ratio_max"]),
        "seamless_loop_vertical": check_seamless_loop(vertical_path, probe_v, config["loop_jump_ratio_max"]),
        "no_flash_or_solid_frames_square": check_no_flash_or_solid_frames(square_path, probe_sq, config),
        "no_flash_or_solid_frames_vertical": check_no_flash_or_solid_frames(vertical_path, probe_v, config),
        "safe_area_square": check_safe_area(square_path, config),
        "safe_area_vertical": check_safe_area(vertical_path, config),
    }

    all_passed = all(c["pass"] for c in checks.values())
    return {"passed": all_passed, "checks": checks, "apple_ready": all_passed}
