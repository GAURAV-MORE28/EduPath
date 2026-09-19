"""Mastery Updater (design §10.4). A **pure function** -- no DB/session, no
gateway/agent import -- over the same `LearnerSkillRecord` shape
`app/gap/engine.py` already uses, so this module is unit-testable with
hand-built fixtures and stays a drop-in "what should the row become" for
whatever repository call actually persists it (`app/assessment/service.py`).

**Mastery is an estimate, never ground truth** (design §10.4: "Display as
bands with confidence, never as ground truth") -- `MasteryOutcome` always
carries `band` and `confidence` alongside the raw `alpha`/`beta`/`estimate`
so no caller can present the number alone as a fact about the learner.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.core.thresholds import (
    MASTERY_BAND_DEVELOPING_MAX,
    MASTERY_BAND_LEARNING_MAX,
    MASTERY_BAND_PROFICIENT_MIN_N_OBS,
    MASTERY_CONFIDENCE_LOW_MAX_N_OBS,
    MASTERY_CONFIDENCE_MEDIUM_MAX_N_OBS,
    MASTERY_CORRECT_WEIGHTS,
    MASTERY_DEFAULT_PRIOR,
    MASTERY_INCORRECT_WEIGHTS,
)
from app.gap.engine import LearnerSkillRecord

# design §10.3: assessed-in-system evidence is always the strongest tier.
# Once any item has been assessed, tier_max can only ever be E3 from then on
# (ARCHITECTURE_CONTRACTS.md §3's tier ordering: E3 > E2 > E1 > E0) -- unlike
# `EvidenceCommitService._upsert_skill_state` (Phase 2), which reseeds
# alpha/beta to a flat prior on a tier upgrade, the Mastery Updater
# *accumulates* per item on top of whatever alpha/beta already existed
# (design's explicit "alpha += w" / "beta += w" formula) -- see
# docs/ARCHITECTURE_CONTRACTS.md §17 for why these two update rules
# deliberately differ.
ASSESSED_TIER = "E3"


@dataclass(frozen=True)
class MasteryOutcome:
    skill_id: str
    alpha: float
    beta: float
    estimate: float  # alpha / (alpha + beta) -- an estimate, not a fact (design §10.4)
    band: str  # unknown | learning | developing | proficient
    confidence: str  # low | medium | high
    n_obs: int
    tier_max: str


def mastery_estimate(alpha: float, beta: float) -> float:
    total = alpha + beta
    return alpha / total if total > 0 else 0.0


def compute_band(estimate: float, n_obs: int, tier_max: str) -> str:
    """design §10.4's band table. "Unknown: n_obs = 0 and tier <= E1" is the
    only band the Mastery Updater itself never produces (it always just
    incremented n_obs to >= 1) -- kept here anyway so the same function can
    classify a *non-assessed* skill state too (e.g. for display), not just
    a freshly-updated one.

    **Decided:** the table lists "Proficient: mastery >= 0.75 and n_obs >=
    3" with no explicit fallback for mastery >= 0.75 but n_obs < 3 -- read
    as "not yet confirmed proficient", which falls back to the next band
    down (`developing`), not silently promoted early on too little evidence.
    """
    if n_obs == 0 and tier_max in ("E0", "E1"):
        return "unknown"
    if estimate < MASTERY_BAND_LEARNING_MAX:
        return "learning"
    if estimate < MASTERY_BAND_DEVELOPING_MAX:
        return "developing"
    return "proficient" if n_obs >= MASTERY_BAND_PROFICIENT_MIN_N_OBS else "developing"


def compute_confidence(n_obs: int) -> str:
    """design §10.4: "low/medium/high from n_obs (0-1/2-3/>=4) and
    consistency across items." **Simplification:** only the `n_obs` half is
    implemented -- a "consistency across items" measure (e.g. variance in
    outcomes) needs per-item history this function deliberately doesn't take
    (it would break the pure-function/no-DB shape); revisit if a later phase
    finds the n_obs-only confidence too coarse."""
    if n_obs <= MASTERY_CONFIDENCE_LOW_MAX_N_OBS:
        return "low"
    if n_obs <= MASTERY_CONFIDENCE_MEDIUM_MAX_N_OBS:
        return "medium"
    return "high"


def update_mastery(existing: LearnerSkillRecord | None, *, skill_id: str, correct: bool, difficulty: str) -> MasteryOutcome:
    """design §10.4: "Update on an assessed item: correct -> alpha += w;
    incorrect -> beta += w, where w depends on item difficulty." `existing`
    is `None` for a skill with no prior evidence-tier state at all (e.g. a
    probe on a never-claimed skill) -- starts from an uninformative
    Beta(1, 1) prior (`MASTERY_DEFAULT_PRIOR`) rather than refusing to
    update.
    """
    alpha = existing.alpha if existing is not None else MASTERY_DEFAULT_PRIOR[0]
    beta = existing.beta if existing is not None else MASTERY_DEFAULT_PRIOR[1]
    n_obs = (existing.n_obs if existing is not None else 0) + 1

    if correct:
        alpha += MASTERY_CORRECT_WEIGHTS[difficulty]
    else:
        beta += MASTERY_INCORRECT_WEIGHTS[difficulty]

    estimate = mastery_estimate(alpha, beta)
    band = compute_band(estimate, n_obs, ASSESSED_TIER)
    confidence = compute_confidence(n_obs)

    return MasteryOutcome(
        skill_id=skill_id,
        alpha=alpha,
        beta=beta,
        estimate=estimate,
        band=band,
        confidence=confidence,
        n_obs=n_obs,
        tier_max=ASSESSED_TIER,
    )
