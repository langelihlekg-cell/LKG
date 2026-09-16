"""
Tier -> visual style presets for the parallax renderer.

This is the file that was missing. `tier` existed everywhere as a billing
label (api/pricing.py, the job schema, the DB column) but was never once
passed into the renderer — every job rendered with the same hardcoded
parallax_gain/zoom_gain regardless of what the customer paid for. That's
why parametric, stylized, and cinematic all produced identical output.

Each preset below has to be recognizably different from its neighbors on
sight, not just "the same motion turned up." The dimensions used to do that:

  parallax_gain / zoom_gain  - how far the camera moves
  orbit                      - single-axis drift (cheap, simple) vs. a
                               two-axis elliptical camera path (dynamic)
  depth_of_field             - far regions (per the depth map) get a soft
                               blur, sharp regions stay crisp -> reads as
                               genuine depth, not just a shifting picture
  vignette                   - radial darkening toward the edges, a classic
                               "this was graded, not just exported" cue
  grade                      - contrast/saturation lift, plus a light
                               teal-shadows/orange-highlights push for the
                               top tier
  glow                       - an animated neon bloom on the brightest
                               regions, hue-cycling across the loop; this is
                               the After Hours-style touch, reserved for
                               cinematic only so it stays a top-tier signal
"""

STYLE_PRESETS = {
    "parametric": {
        "parallax_gain": 0.014,
        "zoom_gain": 0.035,
        "orbit": False,
        "depth_of_field": False,
        "vignette": 0.0,
        "grade": None,
        "glow": None,
    },
    "stylized": {
        "parallax_gain": 0.026,
        "zoom_gain": 0.055,
        "orbit": True,
        "depth_of_field": True,
        "vignette": 0.18,
        "grade": {"contrast": 1.08, "saturation": 1.12},
        "glow": None,
    },
    "cinematic": {
        "parallax_gain": 0.034,
        "zoom_gain": 0.075,
        "orbit": True,
        "depth_of_field": True,
        "vignette": 0.30,
        "grade": {"contrast": 1.14, "saturation": 1.05, "teal_orange": True},
        "glow": {"strength": 0.35},
    },
}


def preset_for_tier(tier: str) -> dict:
    if tier not in STYLE_PRESETS:
        raise ValueError(f"unknown tier: {tier}")
    # Return a copy — render_frame_sequence stashes a precomputed vignette
    # mask into this dict per-render, and presets must never be mutated
    # in place since the same dict object is reused across jobs/tiers.
    return dict(STYLE_PRESETS[tier])
