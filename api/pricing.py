"""
Wholesale pricing: what the distributor is billed per job via this API.
Separate from whatever the distributor chooses to charge artists at retail
(the spec doc references a $9.99 artist-facing add-on as one example retail
point for the parametric tier — that's the distributor's markup decision,
not something this service enforces).
"""

WHOLESALE_PRICE_USD = {
    "parametric": 4.00,   # $2-8 band
    "stylized": 14.00,    # $10-18 band
    "cinematic": 25.00,   # $20-30 band
}

QC_ONLY_PRICE_USD = 0.10  # the Phase 4 "Trojan Horse" wedge price

VOLUME_DISCOUNTS = [
    # (min_jobs_per_month, discount_fraction)
    (1000, 0.10),
    (10000, 0.20),
    (40000, 0.30),  # aligned with the "Preferred Plus" volume tier distributors themselves chase
]


def price_for_tier(tier: str) -> float:
    if tier not in WHOLESALE_PRICE_USD:
        raise ValueError(f"unknown tier: {tier}")
    return WHOLESALE_PRICE_USD[tier]
