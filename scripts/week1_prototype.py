#!/usr/bin/env python3
"""
Week 1 objective (per the phase plan): a script that takes a static square
cover and outputs a seamless looping video.

Usage:
    python3 week1_prototype.py --input cover.png --output out_dir \
        --duration 12 --fps 24 --codec h264 --real-depth

--real-depth requires `pip install torch transformers` and a model download
(needs network — not available in this sandbox, so it defaults to the
classical CPU estimator unless you pass this flag on your own machine).
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "generation"))
from depth_estimator import ClassicalDepthEstimator, DepthAnythingV2Estimator
from parallax_render import render_pair, PRODUCTION_SQUARE, PRODUCTION_VERTICAL, DEMO_SQUARE, DEMO_VERTICAL


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", required=True, help="path to static square cover (PNG/JPG)")
    p.add_argument("--output", required=True, help="output directory")
    p.add_argument("--duration", type=float, default=12.0)
    p.add_argument("--fps", type=int, default=24)
    p.add_argument("--codec", choices=["h264", "prores"], default="h264")
    p.add_argument("--bitrate-mbps", type=float, default=60.0)
    p.add_argument("--real-depth", action="store_true",
                    help="use Depth Anything V2 instead of the classical CPU stand-in")
    p.add_argument("--full-res", action="store_true",
                    help="render at real Apple dims (3840x3840 / 2048x2732) instead of demo scale")
    args = p.parse_args()

    estimator = DepthAnythingV2Estimator() if args.real_depth else ClassicalDepthEstimator()
    dims = (PRODUCTION_SQUARE, PRODUCTION_VERTICAL) if args.full_res else (DEMO_SQUARE, DEMO_VERTICAL)

    print(f"Depth estimator: {type(estimator).__name__}")
    print(f"Target dims: {dims}")

    result = render_pair(
        args.input, args.output, estimator,
        duration_s=args.duration, fps=args.fps, codec=args.codec,
        bitrate_mbps=args.bitrate_mbps, dims=dims,
    )
    print("Done:")
    for k, v in result.items():
        size_kb = os.path.getsize(v) / 1024
        print(f"  {k}: {v}  ({size_kb:.0f} KB)")


if __name__ == "__main__":
    main()
