"""Practice & Assessment API shapes (design §27: `POST /api/learners/me/practice`,
`POST /api/practice/{set_id}/submit`). `AssessmentResult`/`StruggleSignal`
(the core §25.2 schema names) live in `app/schemas/common.py`; everything
here is response/request shape specific to these two endpoints -- same split
`app/schemas/gap.py`/`app/schemas/planning.py` already use.

**Design §18.3: "Client responses never include the misconception_id or the
key. Tags are stripped server-side."** `PracticeItemOut`/`PracticeSetOut`
below are the enforcement point -- they have no field capable of carrying
either.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.common import AssessmentResult, StruggleSignal


class CreatePracticeSetRequest(BaseModel):
    """design §27's `{skill_id?, purpose?}`. `skill_id` is required here
    (design leaves it optional for a "whatever's due" default this project
    does not implement yet -- see Known Issues)."""

    skill_id: str
    purpose: str = "practice"  # practice | probe | resolution-check | prereq-block


class PracticeItemOut(BaseModel):
    """No `is_key`, no `misconception_id` -- design §18.3."""

    item_id: str
    skill_id: str
    difficulty: str
    stem: str
    options: list[str]  # option text only, in a fixed order the client answers by index


class PracticeSetOut(BaseModel):
    set_id: str
    skill_id: str
    purpose: str
    items: list[PracticeItemOut]


class SubmittedAnswerIn(BaseModel):
    item_id: str
    chosen_option: int = Field(ge=0)
    time_sec: int | None = None


class SubmitPracticeRequest(BaseModel):
    """design §27's `{answers, per-item timings}`, plus the optional
    self-reported overload signals design §19.1 lists ("self-reported 'too
    heavy/too easy' (optional)")."""

    answers: list[SubmittedAnswerIn]
    self_reported_overload: bool = False
    planned_vs_actual_ratio: float | None = None
    completion_rate: float | None = None
    retries_trend_rising: bool = False
    new_skills_active: int = 0


class ReflectionOut(BaseModel):
    """Summary of the Reflection pipeline (design §20), when a
    design-§20.2-triggering signal fired this submission: struggle ->
    root cause -> plan patch -> validation -> revision -> resolution probe
    (`app/reflection/service.py`)."""

    root_cause_skill_id: str | None = None
    root_cause_class: str | None = None
    misconception_id: str | None = None
    misconception_status: str | None = None  # confirmed | remediating | resolved | persistent
    remediation_resource_ids: list[str] = []
    operators: list[dict] = []
    plan_revision_id: str | None = None
    degraded: bool = False  # a deterministic policy, not the LLM Reflection Agent, decided this
    needs_attention: bool = False  # both the deterministic and last-resort patches failed validation
    rounds: int = 0
    explanation: str = ""  # learner-facing "why did my plan change"
    decision_id: str | None = None  # DecisionRecord for GET /api/decisions/{id}
    reflection_id: str | None = None


class SubmitPracticeResponse(BaseModel):
    """design §27: "AssessmentResult, signals, optional PlanRevision
    summary" -- `reflection.plan_revision_id` is that optional summary."""

    result: AssessmentResult
    signals: list[StruggleSignal] = []
    reflection: ReflectionOut | None = None
