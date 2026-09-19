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


# design §10.4 "Level mapping (for role requirements)" / ARCHITECTURE_CONTRACTS.md
# §3 "Tier gate for MET" — the Gap Engine's tier-gate thresholds (Phase 4/§13).
# L1 Foundational, L2 Working, L3 Proficient. Keyed by the integer level, since
# `RoleRequirement.required_level` and `SkillEdge.min_level` are plain ints (1-3).
LEVEL_MASTERY_THRESHOLD: dict[int, float] = {1: 0.50, 2: 0.70, 3: 0.85}

# Minimum evidence tier required at each level ("L2: E2 or E3" is expressed via
# `tier_at_least`, since TIER_ORDER already orders E2 below E3).
LEVEL_TIER_REQUIRED: dict[int, str] = {1: "E1", 2: "E2", 3: "E3"}

# Only L3 (Proficient) requires a minimum observation count under the tier gate;
# L1/L2 have no such requirement (ARCHITECTURE_CONTRACTS.md §3).
LEVEL_MIN_N_OBS: dict[int, int] = {3: 3}
