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


class RemediationOut(BaseModel):
    """Summary of the deterministic remediation path (design §20.8), when a
    `repeated_misconception` signal at `confirmed` status fired this
    submission."""

    misconception_id: str
    status: str  # remediating | persistent (start_remediation never returns "resolved" -- only a probe result does)
    started: bool
    skip_reason: str | None = None
    remediation_resource_ids: list[str] = []
    plan_revision_id: str | None = None


class SubmitPracticeResponse(BaseModel):
    """design §27: "AssessmentResult, signals, optional PlanRevision
    summary" -- `remediation.plan_revision_id` is that optional summary."""

    result: AssessmentResult
    signals: list[StruggleSignal] = []
    remediation: RemediationOut | None = None
