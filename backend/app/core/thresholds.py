"""Tunable numeric defaults (ARCHITECTURE_CONTRACTS.md §14: "keep them in
one place... not scattered through code"). Engineering defaults, not
empirical constants — calibrate against an evaluation set once one exists
(design §32); do not present these as derived.
"""
from __future__ import annotations

# design §10.3 / ARCHITECTURE_CONTRACTS.md §3: default Beta-distribution prior
# (alpha successes, beta trials-ish) seeded per evidence tier. E3 has no fixed
# prior -- it accumulates per assessed item (Mastery Updater, Phase 7).
EVIDENCE_TIER_PRIORS: dict[str, tuple[float, float]] = {
    "E0": (0.5, 1.0),
    "E1": (1.0, 1.5),
    "E2": (2.0, 3.0),
}

TIER_ORDER = ["E0", "E1", "E2", "E3"]


def tier_at_least(tier: str, minimum: str) -> bool:
    return TIER_ORDER.index(tier) >= TIER_ORDER.index(minimum)


def max_tier(tiers: list[str]) -> str:
    return max(tiers, key=TIER_ORDER.index)


# design §10.4 mastery bands. Only "unknown" is used by this phase (no
# assessed items exist yet); the rest are recorded here now so the Mastery
# Updater (Phase 7) has one canonical source instead of re-deriving them.
MASTERY_BAND_LEARNING_MAX = 0.55
MASTERY_BAND_DEVELOPING_MAX = 0.75
MASTERY_BAND_PROFICIENT_MIN_N_OBS = 3
