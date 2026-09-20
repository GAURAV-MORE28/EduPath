"""Per-turn Tutor context — everything a tool call needs, assembled once by
`app/tutor/service.py` from the session/auth boundary (`learner_id`) and the
already-loaded `SkillGraphService`, exactly the same "build once, hand to
every node/tool" shape `app/orchestration/graphs.py`'s other graphs use for
their own per-request services. `gap_result` is computed once per turn (a
Gap Engine call is cheap, but recomputing it once per tool call within the
same turn would risk two tools disagreeing if evidence changed mid-turn --
it never does, but there is no reason to allow it).
"""
from __future__ import annotations

from dataclasses import dataclass

from app.gap.engine import GapAnalysisResult
from app.graph.queries import SkillGraphService
from app.repositories.assessment_repository import AssessmentRepository
from app.repositories.catalog_repository import CatalogRepository
from app.repositories.planning_repository import PlanningRepository
from app.repositories.profiling_repository import ProfilingRepository
from app.repositories.reflection_repository import ReflectionRepository
from app.retrieval.service import ResourceRetrievalService


@dataclass
class TutorContext:
    learner_id: str
    role_id: str
    graph: SkillGraphService
    catalog: CatalogRepository
    profiling_repo: ProfilingRepository
    planning_repo: PlanningRepository
    assessment_repo: AssessmentRepository
    reflection_repo: ReflectionRepository
    retrieval_service: ResourceRetrievalService
    gap_result: GapAnalysisResult
