"""Struggle Classifier (design §19.2). **Deterministic, evidence-tiered** --
no LLM anywhere in this module (design §19.5: "the LLM is explicitly not
trusted to... invent new struggle classes... infer cognitive overload from
timing alone... assert mastery"). A pure function, same "unit-testable with
hand-built fixtures, no DB" shape as `app/gap/engine.py`,
`app/retrieval/ranker.py`, `app/planning/validator.py`.

Six classes (design §19.2's table, the Phase 8 brief's explicit list):
`low_score`, `repeated_misconception`, `missing_prerequisite`,
`excessive_difficulty`, `cognitive_overload`, `insufficient_practice`.
Multiple classes may fire from the same evidence; `STRUGGLE_ACTION_PRECEDENCE`
(design §19.2: "Precedence for action: misconception > prerequisite gap >
difficulty mismatch > overload > insufficient practice > low score") picks
one when a caller needs a single primary signal to route on.

**Time and retries are corroborating evidence only, never sole authority**
(design §19.1/§19.5, the Phase 8 brief's explicit instruction): `time_sec`/
`attempt_no` never gate any rule below by themselves -- they only ever
count toward `cognitive_overload`'s "'>= 2 corroborating signals" tally
alongside independent signals (planned-vs-actual ratio, completion rate,
self-report, new-skill concurrency).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.core.thresholds import (
    DIFFICULTY_LABEL_TO_LEVEL,
    EXCESSIVE_DIFFICULTY_MIN_ITEMS,
    EXCESSIVE_DIFFICULTY_SCORE_THRESHOLD,
    INSUFFICIENT_PRACTICE_MAX_N_OBS,
    LOW_SCORE_MIN_ITEMS,
    LOW_SCORE_SEVERE_THRESHOLD,
    LOW_SCORE_THRESHOLD,
    MASTERY_BAND_LEARNING_MAX,
    MISSING_PREREQUISITE_PROBE_THRESHOLD,
    OVERLOAD_COMPLETION_RATE_THRESHOLD,
    OVERLOAD_MIN_CORROBORATING_SIGNALS,
    OVERLOAD_PLANNED_VS_ACTUAL_RATIO,
    REPEATED_MISCONCEPTION_CONFIRM_COUNT,
)
from app.gap.engine import MET

LOW_SCORE = "low_score"
REPEATED_MISCONCEPTION = "repeated_misconception"
MISSING_PREREQUISITE = "missing_prerequisite"
EXCESSIVE_DIFFICULTY = "excessive_difficulty"
COGNITIVE_OVERLOAD = "cognitive_overload"
INSUFFICIENT_PRACTICE = "insufficient_practice"

# design §19.2's closing line, verbatim precedence order.
STRUGGLE_ACTION_PRECEDENCE = (
    REPEATED_MISCONCEPTION,
    MISSING_PREREQUISITE,
    EXCESSIVE_DIFFICULTY,
    COGNITIVE_OVERLOAD,
    INSUFFICIENT_PRACTICE,
    LOW_SCORE,
)


@dataclass(frozen=True)
class ItemOutcome:
    """One item's outcome in the assessment just submitted (design §18.4).
    `misconception_id` is set only when the *chosen* (incorrect) option was
    tagged."""

    item_id: str
    skill_id: str
    difficulty: str  # easy | medium | hard
    correct: bool
    misconception_id: str | None = None
    time_sec: int | None = None
    attempt_no: int = 1


@dataclass(frozen=True)
class StruggleContext:
    """Everything the classifier needs beyond the just-submitted items
    (design §19.1's signal catalogue), already resolved by the caller
    (`app/assessment/service.py`) so this module never touches a session.

    Every field defaults to "no signal" -- a caller with less context than
    the full design still gets a safe (under- rather than over-triggering)
    classification, never a crash.
    """

    skill_id: str  # the assessed skill this submission targets
    current_level: int = 0  # learner's current level on skill_id (design §19.2's excessive_difficulty)
    mastery_estimate: float = 0.0  # post-update estimate for skill_id (insufficient_practice)
    n_obs: int = 0  # post-update assessed-item count for skill_id

    # missing_prerequisite: hard prerequisites of skill_id -> their current gap status.
    hard_prerequisite_status: dict[str, str] = field(default_factory=dict)
    # a recent direct probe score per prerequisite skill_id, if one exists.
    prerequisite_probe_scores: dict[str, float] = field(default_factory=dict)
    # misconception_id -> the skill_id it is ROOTED_IN (design §19.2's "attribution" path).
    misconception_root_skill: dict[str, str] = field(default_factory=dict)

    # repeated_misconception: distinct prior items (within the design's 14-day
    # window) tagged with each misconception_id, *before* this submission.
    prior_misconception_item_counts: dict[str, int] = field(default_factory=dict)

    # cognitive_overload corroborating signals -- design §19.2: "time alone is
    # insufficient", so each is independently optional and the rule requires
    # >= 2 to be true/present at once.
    planned_vs_actual_ratio: float | None = None
    completion_rate: float | None = None
    self_reported_overload: bool = False
    retries_trend_rising: bool = False
    new_skills_active: int = 0
    new_skill_concurrency_cap: int = 3

    # insufficient_practice: whether a resource for this skill was recently completed.
    resource_recently_completed: bool = True


@dataclass
class StruggleSignalEntry:
    """Framework-independent output (mirrors `app/gap/engine.py`'s
    `SkillGapEntry`) -- `app/assessment/service.py` maps this 1:1 to the
    `StruggleSignal` ORM row / Pydantic schema."""

    signal_class: str
    skill_id: str
    confidence: str  # low | medium | high
    evidence_ids: list[str] = field(default_factory=list)  # item_ids (or misconception_id) that fired this signal
    counts: dict[str, float | int | str] = field(default_factory=dict)
    thresholds_used: dict[str, float | int] = field(default_factory=dict)
    signal_id: str = ""  # populated by the caller after persisting (app/assessment/service.py); empty until then


def classify_struggle(items: list[ItemOutcome], context: StruggleContext) -> list[StruggleSignalEntry]:
    """Runs every rule independently; multiple signals may fire. Never
    raises on missing/partial context -- absent signals just don't fire
    (see `StruggleContext`'s field defaults)."""
    signals: list[StruggleSignalEntry] = []

    for fn in (
        _low_score,
        _repeated_misconception,
        _missing_prerequisite,
        _excessive_difficulty,
        _cognitive_overload,
        _insufficient_practice,
    ):
        signals.extend(fn(items, context))
    return signals


def primary_signal(signals: list[StruggleSignalEntry]) -> StruggleSignalEntry | None:
    """design §19.2's action precedence, applied only among *triggering*
    (medium/high confidence) signals -- design §19.3: "Low or suspected ->
    schedule_probe", not a reflection/remediation trigger by itself."""
    triggering = [s for s in signals if s.confidence in ("medium", "high")]
    for cls in STRUGGLE_ACTION_PRECEDENCE:
        for s in triggering:
            if s.signal_class == cls:
                return s
    return None


# ---------------------------------------------------------------------------
# Low score
# ---------------------------------------------------------------------------


def _low_score(items: list[ItemOutcome], context: StruggleContext) -> list[StruggleSignalEntry]:
    relevant = [i for i in items if i.skill_id == context.skill_id]
    if len(relevant) < LOW_SCORE_MIN_ITEMS:
        return []
    score = sum(1 for i in relevant if i.correct) / len(relevant)
    if score >= LOW_SCORE_THRESHOLD:
        return []
    confidence = "medium" if score < LOW_SCORE_SEVERE_THRESHOLD else "low"
    return [
        StruggleSignalEntry(
            signal_class=LOW_SCORE,
            skill_id=context.skill_id,
            confidence=confidence,
            evidence_ids=[i.item_id for i in relevant],
            counts={"score": score, "n_items": len(relevant)},
            thresholds_used={"threshold": LOW_SCORE_THRESHOLD, "min_items": LOW_SCORE_MIN_ITEMS},
        )
    ]


# ---------------------------------------------------------------------------
# Repeated misconception
# ---------------------------------------------------------------------------


def _repeated_misconception(items: list[ItemOutcome], context: StruggleContext) -> list[StruggleSignalEntry]:
    this_attempt_items: dict[str, set[str]] = {}
    for i in items:
        if i.misconception_id is not None:
            this_attempt_items.setdefault(i.misconception_id, set()).add(i.item_id)

    signals: list[StruggleSignalEntry] = []
    for misconception_id, item_ids in this_attempt_items.items():
        prior = context.prior_misconception_item_counts.get(misconception_id, 0)
        total = prior + len(item_ids)
        if total >= REPEATED_MISCONCEPTION_CONFIRM_COUNT:
            status, confidence = "confirmed", "high"
        else:
            status, confidence = "suspected", "low"
        signals.append(
            StruggleSignalEntry(
                signal_class=REPEATED_MISCONCEPTION,
                skill_id=context.skill_id,
                confidence=confidence,
                evidence_ids=sorted(item_ids),
                counts={"misconception_id": misconception_id, "item_count": len(item_ids), "total_occurrences": total, "status": status},
                thresholds_used={"confirm_count": REPEATED_MISCONCEPTION_CONFIRM_COUNT},
            )
        )
    return signals


# ---------------------------------------------------------------------------
# Missing prerequisite
# ---------------------------------------------------------------------------


def _missing_prerequisite(items: list[ItemOutcome], context: StruggleContext) -> list[StruggleSignalEntry]:
    unmet_prereqs = {p for p, status in context.hard_prerequisite_status.items() if status != MET}
    if not unmet_prereqs:
        return []

    signals: list[StruggleSignalEntry] = []
    for prereq in sorted(unmet_prereqs):
        # (a) a direct probe/prereq-block score on the prerequisite itself.
        prereq_items = [i for i in items if i.skill_id == prereq]
        probe_score = context.prerequisite_probe_scores.get(prereq)
        direct_failed = bool(prereq_items) and (sum(1 for i in prereq_items if i.correct) / len(prereq_items)) < MISSING_PREREQUISITE_PROBE_THRESHOLD
        probe_failed = probe_score is not None and probe_score < MISSING_PREREQUISITE_PROBE_THRESHOLD

        # (b) attribution only: a chosen misconception on `skill_id` whose
        # ROOTED_IN skill is this unmet prerequisite.
        attributed_items = [
            i for i in items if i.skill_id == context.skill_id and i.misconception_id is not None
            and context.misconception_root_skill.get(i.misconception_id) == prereq
        ]

        if direct_failed or probe_failed:
            evidence = [i.item_id for i in prereq_items] if prereq_items else []
            signals.append(
                StruggleSignalEntry(
                    signal_class=MISSING_PREREQUISITE,
                    skill_id=context.skill_id,
                    confidence="high",
                    evidence_ids=evidence,
                    counts={"prerequisite_skill_id": prereq, "probe_score": probe_score, "confirmed_by": "probe"},
                    thresholds_used={"probe_threshold": MISSING_PREREQUISITE_PROBE_THRESHOLD},
                )
            )
        elif attributed_items:
            signals.append(
                StruggleSignalEntry(
                    signal_class=MISSING_PREREQUISITE,
                    skill_id=context.skill_id,
                    confidence="medium",
                    evidence_ids=[i.item_id for i in attributed_items],
                    counts={"prerequisite_skill_id": prereq, "confirmed_by": "attribution"},
                    thresholds_used={"probe_threshold": MISSING_PREREQUISITE_PROBE_THRESHOLD},
                )
            )
    return signals


# ---------------------------------------------------------------------------
# Excessive difficulty
# ---------------------------------------------------------------------------


def _excessive_difficulty(items: list[ItemOutcome], context: StruggleContext) -> list[StruggleSignalEntry]:
    # design: "prerequisites MET; no repeated misconception" -- both must hold.
    if any(status != MET for status in context.hard_prerequisite_status.values()):
        return []
    if _repeated_misconception(items, context):
        return []

    above_level = [
        i for i in items if i.skill_id == context.skill_id and DIFFICULTY_LABEL_TO_LEVEL.get(i.difficulty, 0) > context.current_level
    ]
    if len(above_level) < EXCESSIVE_DIFFICULTY_MIN_ITEMS:
        return []
    score = sum(1 for i in above_level if i.correct) / len(above_level)
    if score >= EXCESSIVE_DIFFICULTY_SCORE_THRESHOLD:
        return []
    return [
        StruggleSignalEntry(
            signal_class=EXCESSIVE_DIFFICULTY,
            skill_id=context.skill_id,
            confidence="medium",
            evidence_ids=[i.item_id for i in above_level],
            counts={"score": score, "n_items": len(above_level), "current_level": context.current_level},
            thresholds_used={"threshold": EXCESSIVE_DIFFICULTY_SCORE_THRESHOLD, "min_items": EXCESSIVE_DIFFICULTY_MIN_ITEMS},
        )
    ]


# ---------------------------------------------------------------------------
# Cognitive overload
# ---------------------------------------------------------------------------


def _cognitive_overload(items: list[ItemOutcome], context: StruggleContext) -> list[StruggleSignalEntry]:
    corroborating: dict[str, bool] = {
        "planned_vs_actual": context.planned_vs_actual_ratio is not None
        and context.planned_vs_actual_ratio > OVERLOAD_PLANNED_VS_ACTUAL_RATIO,
        "low_completion": context.completion_rate is not None and context.completion_rate < OVERLOAD_COMPLETION_RATE_THRESHOLD,
        "self_reported": context.self_reported_overload,
        "rising_retries": context.retries_trend_rising,
        "too_many_new_skills": context.new_skills_active > context.new_skill_concurrency_cap,
    }
    fired = [k for k, v in corroborating.items() if v]
    if len(fired) < OVERLOAD_MIN_CORROBORATING_SIGNALS:
        return []
    confidence = "high" if corroborating["self_reported"] else "medium"
    return [
        StruggleSignalEntry(
            signal_class=COGNITIVE_OVERLOAD,
            skill_id=context.skill_id,
            confidence=confidence,
            evidence_ids=[],
            counts={"corroborating_signals": fired, "n_signals": len(fired)},
            thresholds_used={"min_corroborating_signals": OVERLOAD_MIN_CORROBORATING_SIGNALS},
        )
    ]


# ---------------------------------------------------------------------------
# Insufficient practice
# ---------------------------------------------------------------------------


def _insufficient_practice(items: list[ItemOutcome], context: StruggleContext) -> list[StruggleSignalEntry]:
    if context.n_obs >= INSUFFICIENT_PRACTICE_MAX_N_OBS:
        return []
    if context.mastery_estimate >= MASTERY_BAND_LEARNING_MAX:
        return []
    if _repeated_misconception(items, context):
        return []  # errors ARE concentrated on one tag -- that's a different class
    if not context.resource_recently_completed:
        return []
    return [
        StruggleSignalEntry(
            signal_class=INSUFFICIENT_PRACTICE,
            skill_id=context.skill_id,
            confidence="medium",
            evidence_ids=[i.item_id for i in items if i.skill_id == context.skill_id],
            counts={"n_obs": context.n_obs, "mastery_estimate": context.mastery_estimate},
            thresholds_used={"max_n_obs": INSUFFICIENT_PRACTICE_MAX_N_OBS, "mastery_threshold": MASTERY_BAND_LEARNING_MAX},
        )
    ]
