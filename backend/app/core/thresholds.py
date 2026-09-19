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


# design §16-§17: Planner (Phase 5) — Plan Validator (V1-V10) and Fallback
# Planner tunable defaults. Hand-set, not calibrated (ARCHITECTURE_CONTRACTS.md
# §14) -- adjust against design §32's evaluation set once one exists.

# V1 time budget: `hours_budget_minutes = weekly_hours * 60 * WEEKLY_BUDGET_SLACK`.
WEEKLY_BUDGET_SLACK = 0.9
# V9 post-overload headroom: budget * OVERLOAD_BUDGET_FACTOR, cap - 1, "for the next 2 weeks".
OVERLOAD_BUDGET_FACTOR = 0.8
OVERLOAD_CONCURRENCY_REDUCTION = 1

# V5 new-skill concurrency cap: "default 3; 2 for novices or after overload".
NEW_SKILL_CONCURRENCY_CAP = 3
NEW_SKILL_CONCURRENCY_CAP_NOVICE = 2

# V6 session chunking: "single contiguous item <= 60 min".
SESSION_CHUNK_MAX_MINUTES = 60

# design §16.4 fallback planner / §18.1 verify-before-teach probes: "2-3 quick
# MCQs" per probe objective, budgeted a few minutes each.
PROBE_ITEM_COUNT = 3
PROBE_ITEM_MINUTES_PER_ITEM = 3
# Practice pairing (V7) minutes budgeted per practice item the fallback planner attaches.
PRACTICE_ITEM_MINUTES_PER_ITEM = 5
PRACTICE_ITEMS_PER_LESSON = 2

# design §9.4: "fail -> plan_draft with violation list (attempt <= 2)" -- the
# graph-level rule-validation retry loop (distinct from PlannerAgent's own
# internal schema-validation retry, ARCHITECTURE_CONTRACTS.md §6/§11).
PLANNER_MAX_DRAFT_ATTEMPTS = 2


# design §10.4: Mastery Updater (Phase 8) -- Beta-count item weights.
# "difficulty defaults: easy 0.7, medium 1.0, hard 1.3 for correct; the
# reverse for incorrect, since missing an easy item is more informative of
# weakness." Keyed the same way PracticeItem.difficulty already is (easy/medium/hard).
MASTERY_CORRECT_WEIGHTS: dict[str, float] = {"easy": 0.7, "medium": 1.0, "hard": 1.3}
MASTERY_INCORRECT_WEIGHTS: dict[str, float] = {"easy": 1.3, "medium": 1.0, "hard": 0.7}

# An uninformative Beta(1, 1) prior for a skill assessed with no prior
# evidence-tier state at all (e.g. a probe on a skill never claimed) --
# E0-E2 have fixed priors (EVIDENCE_TIER_PRIORS above); E3 "has no fixed
# prior -- it accumulates per assessed item" (design §10.3), so this is only
# the starting point when there is truly nothing to build on.
MASTERY_DEFAULT_PRIOR: tuple[float, float] = (1.0, 1.0)

# design §10.4 band table already defined above
# (MASTERY_BAND_LEARNING_MAX/_DEVELOPING_MAX/_PROFICIENT_MIN_N_OBS).
# Confidence buckets: "low/medium/high from n_obs (0-1 / 2-3 / >=4)".
MASTERY_CONFIDENCE_LOW_MAX_N_OBS = 1
MASTERY_CONFIDENCE_MEDIUM_MAX_N_OBS = 3


# design §18.2: Assessor Agent (Phase 8) -- assembly / generation defaults.
PRACTICE_SET_TARGET_SIZE = 5  # "Assemble a set of ~5 items"
PRACTICE_SET_PREREQ_BLOCK_MIN_ITEMS = 2  # "append >= 2 items on that prerequisite"
ASSESSOR_MAX_RETRIES = 2  # ARCHITECTURE_CONTRACTS.md §11


# design §19.2: Struggle Classifier (Phase 8) -- deterministic thresholds.
# Time/retries are corroborating evidence only (design §19.5), never sole
# authority for any single class below.
LOW_SCORE_THRESHOLD = 0.6
LOW_SCORE_MIN_ITEMS = 3
LOW_SCORE_SEVERE_THRESHOLD = 0.4  # below this, confidence steps up from low to medium

REPEATED_MISCONCEPTION_CONFIRM_COUNT = 2  # ">= 2 distinct items in <= 14 days -> confirmed"
REPEATED_MISCONCEPTION_WINDOW_DAYS = 14

MISSING_PREREQUISITE_PROBE_THRESHOLD = 0.6

EXCESSIVE_DIFFICULTY_SCORE_THRESHOLD = 0.5
EXCESSIVE_DIFFICULTY_MIN_ITEMS = 2
# design §15.1/§10.4: PracticeItem.difficulty (easy/medium/hard) mapped onto
# the same 1-3 integer scale as SkillGap.current_level, so "difficulty >
# level" (design §19.2) is comparable.
DIFFICULTY_LABEL_TO_LEVEL: dict[str, int] = {"easy": 1, "medium": 2, "hard": 3}

OVERLOAD_MIN_CORROBORATING_SIGNALS = 2  # "time alone is insufficient"
OVERLOAD_PLANNED_VS_ACTUAL_RATIO = 1.5  # "> 1.5x in a week"
OVERLOAD_COMPLETION_RATE_THRESHOLD = 0.6  # "completion < 60% of items"

INSUFFICIENT_PRACTICE_MAX_N_OBS = 4  # "n_obs < 4"

# design §19.4: at most one reflection/remediation-triggered revision per
# (learner, skill or misconception) per cooldown window, unless new assessed
# evidence exists.
STRUGGLE_REVISION_COOLDOWN_HOURS = 24

# design §20.8: "after two failed remediation cycles -> persistent... does
# not loop indefinitely."
MAX_REMEDIATION_CYCLES = 2
