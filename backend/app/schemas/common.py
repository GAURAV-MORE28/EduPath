"""Core schema stubs (ARCHITECTURE_CONTRACTS.md §6, design doc §25.2).

Phase 1 only needs these to exist as typed placeholders so the orchestration
skeleton, gateway, and API layer have something concrete to import. Full field
lists are defined when each owning phase (2, 4, 5, 7, 8, 9) is implemented —
do not add business fields here ahead of that work.

`SkillGap` and `LearningObjective` got their real §25.2 field lists in Phase
4 (Gap Engine, `app/gap/engine.py`) — see `app/schemas/gap.py` for the full
gap-report response shape built on top of them. `WeeklyPlan`/`PlanItem` got
theirs in Phase 5 (Planner, `app/planning/`). `AssessmentResult`/
`StruggleSignal` got theirs in Phase 8 (Assessment, `app/assessment/`).
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class LearnerState(BaseModel):
    learner_id: str
    data: dict[str, Any] = {}


class SkillState(BaseModel):
    learner_id: str
    skill_id: str
    data: dict[str, Any] = {}


class SkillGap(BaseModel):
    """design §25.2. Produced by the Gap Engine (`app/gap/engine.py`'s
    `SkillGapEntry`, mapped 1:1 by `app/api/v1/gap.py`). `status` is the
    user-facing status (`BLOCKED` overlays the raw diagnosis); `gap_type` is
    that raw diagnosis (`met`/`weak`/`unverified`/`missing`) underneath it.
    """

    skill_id: str
    label: str
    status: str  # MET | WEAK | UNVERIFIED | MISSING | BLOCKED
    gap_type: str
    required_level: int
    current_level: int
    blocked_by: list[str] = []
    root_of: list[str] = []
    priority: float = 0.0
    ordering_layer: int = -1
    evidence_ids: list[str] = []
    audit_flags: list[str] = []


class LearningObjective(BaseModel):
    """design §25.2/§13.5. `objective_type="probe"` is how the Gap Engine
    implements verify-before-teach for `UNVERIFIED` gaps (Phase 5 brief)."""

    objective_id: str
    skill_id: str
    from_status: str
    objective_type: str  # "probe" | "lesson"
    target_level: int
    priority: float
    prerequisite_objective_ids: list[str] = []
    acceptance_criteria: dict[str, Any] = {}
    est_minutes_low: int | None = None
    est_minutes_high: int | None = None
    reason_ref: str = ""


class ResourceRecommendation(BaseModel):
    """design §25.2/§15.3. Produced by the Resource Retriever/Ranker
    (`app/retrieval/ranker.py`'s `ResourceRecommendation` dataclass, mapped
    1:1 by whichever caller needs the Pydantic shape — no API route
    consumes this directly yet; design §27 has no endpoint row for this
    service, only the future Planner calling it internally)."""

    resource_id: str
    objective_id: str | None = None
    skill_id: str = ""
    score: float = 0.0
    score_breakdown: dict[str, float] = {}
    eligibility_checks: dict[str, bool] = {}
    provenance: dict[str, Any] = {}


class PlanItemReason(BaseModel):
    """design §16.6: "Every PlanItem.reason is composed from IDs... The LLM
    is asked only to *phrase* these; the IDs are attached deterministically."
    `text` is the only display-only (LLM-authored) field; everything else is
    ID-attached by the deterministic planning pipeline."""

    evidence_ids: list[str] = []
    graph_path: list[str] | None = None
    decision_id: str | None = None
    text: str = ""  # display-only


class PlanItem(BaseModel):
    """design §25.2/§28. `practice_item_ids` is an addition beyond §25.2's
    single `practice_set_id?` — no `PracticeSet` generation service exists
    yet (design §18, Assessor, Phase 7 in this project's numbering), so this
    stores the underlying curated `PracticeItem` IDs directly rather than a
    set this project cannot yet build (same "addition beyond the conceptual
    list" latitude Phase 3 used for `GraphMeta`)."""

    item_id: str
    type: str  # resource | practice | project | probe | review
    objective_id: str
    skill_id: str
    resource_id: str | None = None
    practice_item_ids: list[str] = []
    est_minutes: int
    difficulty: int
    day_slot: int
    depends_on: list[str] = []
    reason: PlanItemReason = PlanItemReason()
    status: str = "planned"  # planned | done | skipped


class WeeklyPlan(BaseModel):
    """design §25.2/§28."""

    plan_id: str
    learner_id: str
    week_index: int
    hours_budget: float
    revision_no: int = 1
    status: str = "draft"  # draft | committed
    degraded: bool = False
    items: list[PlanItem] = []
    overall_reason: str = ""  # display-only


class AssessmentItemResult(BaseModel):
    """design §18.4/§25.2's per-item `AssessmentResult.items[]` entry.
    `misconception_id` is set only when the chosen (incorrect) option was
    tagged to one — design §18.3: never the *key*, only ever attached to a
    wrong answer actually chosen."""

    item_id: str
    skill_id: str
    difficulty: str  # easy | medium | hard
    chosen_option: int
    correct: bool
    misconception_id: str | None = None
    time_sec: int | None = None
    attempt_no: int = 1


class AssessmentResult(BaseModel):
    """design §25.2/§18.4."""

    assessment_id: str
    learner_id: str
    skill_id: str
    purpose: str  # practice | probe | resolution-check | prereq-block
    items: list[AssessmentItemResult] = []
    score: float = 0.0
    prereq_block_score: float | None = None
    submitted_at: str = ""


class StruggleSignal(BaseModel):
    """design §25.2/§19.2. `signal_class` intentionally avoids the Python
    keyword `class` (ARCHITECTURE_CONTRACTS.md §12: field values keep the
    design doc's own casing; the Python attribute name is this project's
    own naming choice, same as `app/gap/engine.py`'s `gap_type`)."""

    signal_id: str
    learner_id: str
    signal_class: str  # low_score | repeated_misconception | missing_prerequisite | excessive_difficulty | cognitive_overload | insufficient_practice
    skill_id: str
    confidence: str = "low"  # low | medium | high
    evidence_ids: list[str] = []
    counts: dict[str, Any] = {}
    thresholds_used: dict[str, Any] = {}
    status: str = "open"  # open | closed


class ReflectionResult(BaseModel):
    reflection_id: str
    learner_id: str
    operators: list[dict[str, Any]] = []


class ReplanRequest(BaseModel):
    plan_id: str
    reason: str


class ProgressReport(BaseModel):
    learner_id: str
    data: dict[str, Any] = {}
