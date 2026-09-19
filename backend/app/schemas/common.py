"""Core schema stubs (ARCHITECTURE_CONTRACTS.md §6, design doc §25.2).

Phase 1 only needs these to exist as typed placeholders so the orchestration
skeleton, gateway, and API layer have something concrete to import. Full field
lists are defined when each owning phase (2, 4, 5, 7, 8, 9) is implemented —
do not add business fields here ahead of that work.

`SkillGap` and `LearningObjective` got their real §25.2 field lists this
phase (Gap Engine, `app/gap/engine.py`) — see `app/schemas/gap.py` for the
full gap-report response shape built on top of them.
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


class WeeklyPlan(BaseModel):
    plan_id: str
    learner_id: str
    week_index: int
    items: list["PlanItem"] = []


class PlanItem(BaseModel):
    item_id: str
    skill_id: str
    data: dict[str, Any] = {}


class AssessmentResult(BaseModel):
    assessment_id: str
    learner_id: str
    score: float | None = None
    data: dict[str, Any] = {}


class StruggleSignal(BaseModel):
    signal_id: str
    learner_id: str
    skill_id: str
    signal_class: str
    confidence: float = 0.0


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


WeeklyPlan.model_rebuild()
