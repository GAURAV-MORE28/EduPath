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


# design §15.3: Resource Retriever/Ranker (Phase 6) deterministic ranking
# weights. `score = sum(RESOURCE_RANK_WEIGHTS[k] * component[k]) -
# RESOURCE_PRIOR_FAILURE_PENALTY (if applicable)`. Hand-set defaults per the
# design doc; adjust against a labeled query set (design §32) once one exists.
RESOURCE_RANK_WEIGHTS: dict[str, float] = {
    "level_fit": 0.35,
    "quality": 0.20,
    "modality_pref": 0.15,
    "relevance": 0.15,
    "duration_fit": 0.10,
    "novelty": 0.05,
}

# "penalty_if_prior_failure: a resource followed by failure on the same skill."
RESOURCE_PRIOR_FAILURE_PENALTY = 0.3

# `quality` component: curation_tier base score (design §15.1's curated/
# community/unvetted tiers) multiplied by a `last_verified_at` recency factor.
RESOURCE_QUALITY_TIER_BASE: dict[str, float] = {"curated": 1.0, "community": 0.6, "unvetted": 0.2}
RESOURCE_QUALITY_RECENCY_FRESH_DAYS = 180  # verified within this window -> full recency credit
RESOURCE_QUALITY_RECENCY_STALE_DAYS = 365  # verified within this window -> partial credit, else floor
RESOURCE_QUALITY_RECENCY_STALE_FACTOR = 0.75
RESOURCE_QUALITY_RECENCY_FLOOR_FACTOR = 0.5  # applied beyond the stale window, or when never verified

# Reciprocal Rank Fusion's smoothing constant (design §14.3 point 3), standard default.
RRF_K = 60

# Default active-time budget per session when the learner hasn't set
# `IntakePreferences.session_length_min` (design §15.3's "fits session cap").
DEFAULT_SESSION_CAP_MINUTES = 45
