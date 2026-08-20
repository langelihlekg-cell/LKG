#!/usr/bin/env python3
"""
End-to-end pipeline test — no pytest dependency, just plain asserts, so it
runs anywhere Python + ffmpeg + the packages in generation/requirements.txt
(minus torch/transformers) are available.

Covers:
  1. A genuinely compliant render passes every QC check.
  2. QC correctly REJECTS a file with an injected defect (audio track) while
     leaving unrelated checks unaffected — proving the suite discriminates
     rather than rubber-stamping.
  3. QC correctly rejects an under-spec render when checked against full
     production dimensions — proving it doesn't silently pass wrong output.

Run: python3 tests/test_pipeline.py
"""
import os
import sys
import shutil
import subprocess
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "generation"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "qc"))

from depth_estimator import ClassicalDepthEstimator
from parallax_render import render_pair, DEMO_SQUARE, DEMO_VERTICAL, PRODUCTION_SQUARE
from qc_suite import run_qc_suite, CONFIG


def make_test_cover(path: str, size: int = 600):
    import numpy as np
    from PIL import Image, ImageDraw
    bg = np.zeros((size, size, 3), dtype=np.uint8)
    for y in range(size):
        t = y / size
        bg[y, :, 0] = int(20 + t * 140)
        bg[y, :, 1] = int(10 + t * 20)
        bg[y, :, 2] = int(40 + t * 60)
    img = Image.fromarray(bg)
    draw = ImageDraw.Draw(img)
    draw.ellipse([size * 0.2, size * 0.17, size * 0.8, size * 0.77], fill=(15, 15, 20))
    draw.polygon([(size * 0.5, size * 0.23), (size * 0.7, size * 0.63), (size * 0.3, size * 0.63)],
                 fill=(240, 200, 60))
    img.save(path)


def test_compliant_render_passes(tmp_dir):
    cover = os.path.join(tmp_dir, "cover.png")
    make_test_cover(cover)

    out_dir = os.path.join(tmp_dir, "out")
    estimator = ClassicalDepthEstimator()
    assets = render_pair(cover, out_dir, estimator, duration_s=3.0, fps=12,
                          codec="h264", bitrate_mbps=6.0, dims=(DEMO_SQUARE, DEMO_VERTICAL))

    demo_config = dict(CONFIG)
    demo_config["square_resolution"] = DEMO_SQUARE
    demo_config["vertical_resolution"] = DEMO_VERTICAL
    demo_config["bitrate_range_mbps"] = (5, 7)
    demo_config["duration_range_s"] = (2, 35)

    report = run_qc_suite(assets["square_1x1"], assets["vertical_3x4"], cover, demo_config)
    assert report["passed"], f"expected a clean pass, got failures: " \
        f"{[k for k,v in report['checks'].items() if not v['pass']]}"
    print("  [PASS] compliant render passes every QC check")
    return assets, cover


def test_audio_defect_is_caught(tmp_dir, assets, cover):
    broken = os.path.join(tmp_dir, "broken_with_audio.mov")
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
        "-i", assets["square_1x1"], "-c:v", "copy", "-c:a", "aac", "-shortest", "-t", "3",
        broken,
    ], capture_output=True, check=True)

    demo_config = dict(CONFIG)
    demo_config["square_resolution"] = DEMO_SQUARE
    demo_config["vertical_resolution"] = DEMO_VERTICAL
    demo_config["bitrate_range_mbps"] = (0, 999)  # isolate the audio check specifically
    demo_config["duration_range_s"] = (2, 35)

    report = run_qc_suite(broken, assets["vertical_3x4"], cover, demo_config)
    assert not report["checks"]["audio_track_absent_square"]["pass"], "should have caught the injected audio track"
    assert report["checks"]["resolution_1x1"]["pass"], "unrelated checks shouldn't be affected by the audio defect"
    print("  [PASS] injected audio-track defect is caught, unrelated checks unaffected")


def test_wrong_resolution_is_caught(assets, cover):
    # demo files are DEMO_SQUARE-sized; checking against real production dims
    # must fail resolution, proving the suite doesn't rubber-stamp everything.
    report = run_qc_suite(assets["square_1x1"], assets["vertical_3x4"],
                           cover, CONFIG)  # CONFIG = full production thresholds
    assert not report["checks"]["resolution_1x1"]["pass"]
    assert not report["passed"]
    print("  [PASS] under-spec resolution correctly fails against production config")


if __name__ == "__main__":
    tmp = tempfile.mkdtemp(prefix="motion_artwork_test_")
    try:
        print("Running pipeline tests...")
        assets, cover = test_compliant_render_passes(tmp)
        test_audio_defect_is_caught(tmp, assets, cover)
        test_wrong_resolution_is_caught(assets, cover)
        print("\nAll tests passed.")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
