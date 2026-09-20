"""Read-model response shapes for the frontend (Phase 11).

Everything here is a read-only projection of data other phases already own
(catalog, evidence, plans, revisions). No decision logic lives in these
schemas or their routes (`app/api/v1/views.py`): the frontend needs labels,
resource metadata, evidence spans and revision history that the write-path
endpoints do not return, and must never hard-code them.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import PlanItem, SkillGap


class RoleOut(BaseModel):
    role_id: str
    title: str
    description: str = ""
    required_skill_count: int = 0


class SkillOut(BaseModel):
    skill_id: str
    label: str
    kind: str
    area: str
    description: str = ""


class ResourceOut(BaseModel):
    resource_id: str
    title: str
    url: str
    provider: str
    type: str
    difficulty: int
    duration_min: int
    modality: str
    learning_objective_text: str = ""
    cost: str = ""
    link_status: str = ""
    curation_tier: str = ""


class EvidenceOut(BaseModel):
    evidence_id: str
    skill_id: str
    skill_label: str
    tier: str  # E0 | E1 | E2 | E3
    source_type: str  # intake | document | github | assessment
    document_id: str | None = None
    document_label: str | None = None  # file name (never a server path) or repo URL
    span_text: str = ""
    span_offsets: dict[str, int] | None = None
    verified: bool = False
    created_at: str = ""


class MasteryOut(BaseModel):
    estimate: float
    band: str
    confidence: str
    tier_max: str
    n_obs: int


class PrerequisiteOut(BaseModel):
    skill_id: str
    label: str
    status: str | None = None  # gap status when the skill is in the role's scope
    min_level: int | None = None


class MisconceptionOut(BaseModel):
    misconception_id: str
    description: str
    signature: str = ""
    root_skill_id: str
    root_skill_label: str
    learner_status: str | None = None  # suspected | confirmed | remediating | resolved | persistent


class RoleRequirementOut(BaseModel):
    role_id: str
    required_level: int
    weight: int  # core 3 / important 2 / nice 1


class SkillPlanItemOut(BaseModel):
    item_id: str
    type: str
    status: str
    day_slot: int
    est_minutes: int


class SkillDetailOut(BaseModel):
    skill: SkillOut
    gap: SkillGap | None = None
    mastery: MasteryOut | None = None
    role_requirement: RoleRequirementOut | None = None
    evidence: list[EvidenceOut] = Field(default_factory=list)
    prerequisites: list[PrerequisiteOut] = Field(default_factory=list)
    dependents: list[PrerequisiteOut] = Field(default_factory=list)
    resources: list[ResourceOut] = Field(default_factory=list)
    misconceptions: list[MisconceptionOut] = Field(default_factory=list)
    plan_items: list[SkillPlanItemOut] = Field(default_factory=list)


class PlanRevisionOut(BaseModel):
    revision_id: str
    plan_id: str
    revision_no: int
    parent_revision_id: str | None = None
    cause_type: str  # initial | reflection | user_override | ...
    cause_ref: str = ""
    operators: list[dict[str, Any]] = Field(default_factory=list)
    diff: dict[str, Any] = Field(default_factory=dict)
    degraded: bool = False
    overall_reason: str = ""
    created_at: str = ""
    reverted_by: str | None = None
    is_current: bool = False
    decision_id: str | None = None  # the reflection DecisionRecord that produced it, if any


class PlanRevisionDetailOut(PlanRevisionOut):
    items: list[PlanItem] = Field(default_factory=list)


class UpdatePlanItemRequest(BaseModel):
    status: str = Field(pattern="^(planned|done|skipped)$")
