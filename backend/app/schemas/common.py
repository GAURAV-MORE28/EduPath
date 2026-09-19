"""Core schema stubs (ARCHITECTURE_CONTRACTS.md §6, design doc §25.2).

Phase 1 only needs these to exist as typed placeholders so the orchestration
skeleton, gateway, and API layer have something concrete to import. Full field
lists are defined when each owning phase (2, 4, 5, 7, 8, 9) is implemented —
do not add business fields here ahead of that work.
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
    skill_id: str
    status: str  # MET | WEAK | UNVERIFIED | MISSING | BLOCKED
    data: dict[str, Any] = {}


class LearningObjective(BaseModel):
    objective_id: str
    skill_id: str
    data: dict[str, Any] = {}


class ResourceRecommendation(BaseModel):
    resource_id: str
    score: float = 0.0
    data: dict[str, Any] = {}


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
