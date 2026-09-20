"""G4 Tutor orchestration glue — mirrors `app/planning/service.py`'s split:
build the per-turn deterministic services + `TutorContext` from the current
catalog/graph/learner state, compile and invoke the G4 graph
(`app/orchestration/graphs.py::build_tutor_graph`), and return a plain
`ChatAnswer`. Nothing here writes to the database — the Tutor is read-only
by construction (ARCHITECTURE_CONTRACTS.md §2), so unlike G1/G2/Reflection
there is no commit step at the end of this module.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.tutor import TutorAgent
from app.core.thresholds import TUTOR_MAX_COMPOSE_ATTEMPTS
from app.gap.engine import EvidenceRecord, GapAnalysisResult, LearnerSkillRecord, analyze_gaps
from app.gateway.embedding_gateway import get_embedding_gateway
from app.gateway.llm_gateway import LLMGateway
from app.graph.queries import SkillGraphService
from app.orchestration.graphs import build_tutor_graph
from app.orchestration.state import RunState
from app.provenance.citations import verify_citations
from app.repositories.assessment_repository import AssessmentRepository
from app.repositories.catalog_repository import CatalogRepository
from app.repositories.planning_repository import PlanningRepository
from app.repositories.profiling_repository import ProfilingRepository
from app.repositories.reflection_repository import ReflectionRepository
from app.retrieval.service import ResourceRetrievalService
from app.tutor.conservative import build_conservative_answer
from app.tutor.context import TutorContext
from app.tutor.report_builder import ProgressReportData
from app.tutor.tools import progress_report_to_tool_result


class NoLearnerProfileError(Exception):
    pass


@dataclass
class ChatAnswer:
    answer: str
    citations: list[str] = field(default_factory=list)
    degraded: bool = False
    conservative: bool = False
    tool_calls_used: int = 0


async def _build_gap_result(profiling_repo: ProfilingRepository, graph: SkillGraphService, learner_id: str, role_id: str) -> GapAnalysisResult:
    skill_states = await profiling_repo.list_skill_states_for_learner(learner_id)
    evidence_rows = await profiling_repo.list_evidence_for_learner(learner_id)
    skill_records = [
        LearnerSkillRecord(skill_id=s.skill_id, alpha=s.alpha, beta=s.beta, tier_max=s.tier_max, n_obs=s.n_obs)
        for s in skill_states
    ]
    evidence_records = [
        EvidenceRecord(evidence_id=e.evidence_id, skill_id=e.skill_id, tier=e.tier) for e in evidence_rows
    ]
    return analyze_gaps(role_id, skill_records, evidence_records, graph)


async def build_tutor_context(session: AsyncSession, graph: SkillGraphService, learner_id: str) -> TutorContext:
    profiling_repo = ProfilingRepository(session)
    profile = await profiling_repo.get_learner_profile(learner_id)
    if profile is None:
        raise NoLearnerProfileError(f"no learner profile for {learner_id!r}")

    gap_result = await _build_gap_result(profiling_repo, graph, learner_id, profile.target_role_id)
    catalog = CatalogRepository(session)
    return TutorContext(
        learner_id=learner_id,
        role_id=profile.target_role_id,
        graph=graph,
        catalog=catalog,
        profiling_repo=profiling_repo,
        planning_repo=PlanningRepository(session),
        assessment_repo=AssessmentRepository(session),
        reflection_repo=ReflectionRepository(session),
        retrieval_service=ResourceRetrievalService(catalog, graph, get_embedding_gateway()),
        gap_result=gap_result,
    )


async def run_chat(
    *,
    session: AsyncSession,
    graph: SkillGraphService,
    llm_gateway: LLMGateway,
    learner_id: str,
    message: str,
    skill_id_hint: str | None = None,
    decision_id_hint: str | None = None,
) -> ChatAnswer:
    ctx = await build_tutor_context(session, graph, learner_id)
    tutor_agent = TutorAgent(llm_gateway)
    compiled = build_tutor_graph(ctx=ctx, tutor_agent=tutor_agent)

    state: RunState = {
        "run_id": str(uuid.uuid4()),
        "learner_id": learner_id,
        "graph": "G4_tutor",
        "status": "running",
        "counters": {},
        "data": {"message": message, "skill_id_hint": skill_id_hint, "decision_id_hint": decision_id_hint},
    }
    result = await compiled.ainvoke(state)
    data = result["data"]
    return ChatAnswer(
        answer=data["final_answer"],
        citations=data["final_citations"],
        degraded=data["final_degraded"],
        conservative=data.get("conservative", False),
        tool_calls_used=len(data.get("tool_calls", [])),
    )


async def narrate_progress(llm_gateway: LLMGateway, report: ProgressReportData) -> tuple[str, bool]:
    """design's "Report Builder + Tutor narration" (§25.2's
    `ProgressReport.narrative`, display-only). Collapses `build_tutor_graph`'s
    `compose_answer -> verify_citations -> [regenerate once] -> conservative`
    ladder down to its essentials, since there is exactly one tool result
    here (the report itself) rather than a rule-based tool plan to run
    first. Returns `(narrative_text, degraded)`.
    """
    tool_result = progress_report_to_tool_result(report)
    context_blocks = {tool_result.tool: tool_result.data}
    tutor_agent = TutorAgent(llm_gateway)

    missing_ids: list[str] | None = None
    for _attempt in range(TUTOR_MAX_COMPOSE_ATTEMPTS):
        result = await tutor_agent.run(
            str(uuid.uuid4()),
            {"question": "Summarize my learning progress so far.", "context_blocks": context_blocks, "missing_ids": missing_ids},
        )
        if result["degraded"]:
            break  # no provider configured -- won't change on retry
        draft = result["draft"]
        check = verify_citations(draft.citations, tool_result.citable_ids)
        if check.passed:
            return draft.answer, False
        missing_ids = check.invalid_ids

    answer, _citations = build_conservative_answer([tool_result])
    return answer, True
