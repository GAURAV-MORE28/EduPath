"""G2 Planning orchestration glue -- mirrors `app/profiling/onboarding.py`'s
split between "pure algorithm" and "DB/gateway glue". Builds the per-run
deterministic services + Planner Agent from the current catalog/graph,
compiles and invokes the G2 graph (`app/orchestration/graphs.py`), and
persists its finalized result as `WeeklyPlan`/`PlanRevision`/`PlanItem` rows
-- design's `commit_plan` node, done outside the graph for the same reason
Phase 2's `PendingClaim` write is (see `build_planning_graph`'s docstring).

Two entry points, matching the Planner Agent's two modes (design §8.2):
`create_plan` (draft) and `patch_existing_plan` (patch, design §16/§20 --
Reflection, Phase 8, is this function's intended future caller; this phase
only builds the capability).
"""
from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.planner import PlannerAgent
from app.core.thresholds import DEFAULT_SESSION_CAP_MINUTES, NEW_SKILL_CONCURRENCY_CAP
from app.db.models import PlanItem as PlanItemRow
from app.db.models import PlanRevision as PlanRevisionRow
from app.db.models import WeeklyPlan as WeeklyPlanRow
from app.gap.engine import EvidenceRecord, LearnerSkillRecord
from app.gateway.embedding_gateway import EmbeddingGateway
from app.gateway.llm_gateway import LLMGateway
from app.graph.queries import SkillGraphService
from app.orchestration.graphs import build_planning_graph
from app.orchestration.state import RunState
from app.planning.validator import effective_budget_minutes
from app.repositories.catalog_repository import CatalogRepository
from app.repositories.planning_repository import PlanningRepository
from app.repositories.profiling_repository import ProfilingRepository
from app.retrieval.service import ResourceRetrievalService
from app.schemas.common import PlanItem, WeeklyPlan


class UnknownPlanError(Exception):
    pass


async def _build_records(
    profiling_repo: ProfilingRepository, learner_id: str
) -> tuple[list[LearnerSkillRecord], list[EvidenceRecord]]:
    skill_states = await profiling_repo.list_skill_states_for_learner(learner_id)
    evidence_rows = await profiling_repo.list_evidence_for_learner(learner_id)
    skill_records = [
        LearnerSkillRecord(skill_id=s.skill_id, alpha=s.alpha, beta=s.beta, tier_max=s.tier_max, n_obs=s.n_obs)
        for s in skill_states
    ]
    evidence_records = [
        EvidenceRecord(evidence_id=e.evidence_id, skill_id=e.skill_id, tier=e.tier) for e in evidence_rows
    ]
    return skill_records, evidence_records


async def _run_graph(
    *,
    session: AsyncSession,
    graph_service: SkillGraphService,
    llm_gateway: LLMGateway,
    embedding_gateway: EmbeddingGateway,
    learner_id: str,
    role_id: str,
    hours_budget_minutes: float,
    mode: str,
    existing_items: list[dict] | None,
    operators: list[dict] | None,
    modality_order: list[str] | None,
    language: str,
    session_cap_minutes: int,
    new_skill_cap: int,
) -> tuple[RunState, str]:
    catalog = CatalogRepository(session)
    profiling_repo = ProfilingRepository(session)
    retrieval_service = ResourceRetrievalService(catalog, graph_service, embedding_gateway)
    planner_agent = PlannerAgent(llm_gateway)

    skill_records, evidence_records = await _build_records(profiling_repo, learner_id)

    graph = build_planning_graph(
        graph_service=graph_service,
        planner_agent=planner_agent,
        catalog=catalog,
        retrieval_service=retrieval_service,
    )

    run_id = str(uuid.uuid4())
    initial_state: RunState = {
        "run_id": run_id,
        "learner_id": learner_id,
        "graph": "G2_planning",
        "status": "running",
        "counters": {},
        "data": {
            "role_id": role_id,
            "skill_records": skill_records,
            "evidence_records": evidence_records,
            "hours_budget_minutes": hours_budget_minutes,
            "mode": mode,
            "existing_items": existing_items,
            "operators": operators,
            "modality_order": modality_order,
            "language": language,
            "session_cap_minutes": session_cap_minutes,
            "new_skill_cap": new_skill_cap,
        },
    }
    final_state = await graph.ainvoke(initial_state)
    return final_state, run_id


async def _persist_plan(
    *,
    session: AsyncSession,
    learner_id: str,
    week_index: int,
    weekly_hours: float,
    final_state: RunState,
    cause_type: str,
    cause_ref: str,
    operators: list[dict] | None,
    parent_revision_id: str | None,
    existing_plan_id: str | None,
) -> WeeklyPlan:
    d = final_state["data"]
    final_items: list[PlanItem] = d["final_items"]
    overall_reason: str = d["final_overall_reason"]
    degraded: bool = d["final_degraded"]

    repo = PlanningRepository(session)

    if existing_plan_id is not None:
        plan_row = await repo.get_plan(existing_plan_id)
        if plan_row is None:
            raise UnknownPlanError(f"unknown plan_id {existing_plan_id!r}")
    else:
        plan_row = await repo.create_weekly_plan(
            WeeklyPlanRow(learner_id=learner_id, week_index=week_index, hours_budget=weekly_hours, status="committed")
        )

    prior_revisions = await repo.list_revisions(plan_row.plan_id)
    revision_no = len(prior_revisions) + 1

    revision_row = await repo.create_revision(
        PlanRevisionRow(
            plan_id=plan_row.plan_id,
            revision_no=revision_no,
            parent_revision_id=parent_revision_id,
            cause_type=cause_type,
            cause_ref=cause_ref,
            operators=operators or [],
            diff={},
            degraded=degraded,
            overall_reason=overall_reason,
        )
    )

    item_rows = [
        PlanItemRow(
            item_id=item.item_id,
            plan_id=plan_row.plan_id,
            revision_id=revision_row.revision_id,
            type=item.type,
            objective_id=item.objective_id,
            skill_id=item.skill_id,
            resource_id=item.resource_id,
            practice_item_ids=item.practice_item_ids,
            est_minutes=item.est_minutes,
            difficulty=item.difficulty,
            day_slot=item.day_slot,
            depends_on=item.depends_on,
            reason=item.reason.model_dump(mode="json"),
            status=item.status,
        )
        for item in final_items
    ]
    if item_rows:
        await repo.create_items(item_rows)

    plan_row.status = "committed"
    plan_row.current_revision_id = revision_row.revision_id

    return WeeklyPlan(
        plan_id=plan_row.plan_id,
        learner_id=learner_id,
        week_index=plan_row.week_index,
        hours_budget=plan_row.hours_budget,
        revision_no=revision_row.revision_no,
        status=plan_row.status,
        degraded=degraded,
        items=final_items,
        overall_reason=overall_reason,
    )


async def create_plan(
    *,
    session: AsyncSession,
    graph_service: SkillGraphService,
    llm_gateway: LLMGateway,
    embedding_gateway: EmbeddingGateway,
    learner_id: str,
    role_id: str,
    week_index: int,
    weekly_hours: float,
    modality_order: list[str] | None = None,
    language: str = "",
    session_cap_minutes: int = DEFAULT_SESSION_CAP_MINUTES,
    new_skill_cap: int = NEW_SKILL_CONCURRENCY_CAP,
    dry_run: bool = False,
) -> WeeklyPlan:
    """design §27's `POST /api/learners/me/plans` -- G2 Planning's
    `create_plan` (draft) mode end to end: build objectives -> retrieve
    candidates -> plan_draft -> validate -> (fallback if needed) -> commit.
    `dry_run=True` runs the same graph but writes nothing (design §16.5's
    optional O1 "what-if" flag -- no new logic, only the flag; the returned
    `WeeklyPlan.plan_id` is a synthetic, non-persisted placeholder)."""
    hours_budget_minutes = effective_budget_minutes(weekly_hours)
    final_state, run_id = await _run_graph(
        session=session,
        graph_service=graph_service,
        llm_gateway=llm_gateway,
        embedding_gateway=embedding_gateway,
        learner_id=learner_id,
        role_id=role_id,
        hours_budget_minutes=hours_budget_minutes,
        mode="draft",
        existing_items=None,
        operators=None,
        modality_order=modality_order,
        language=language,
        session_cap_minutes=session_cap_minutes,
        new_skill_cap=new_skill_cap,
    )

    if dry_run:
        d = final_state["data"]
        return WeeklyPlan(
            plan_id=f"dry-run-{run_id}",
            learner_id=learner_id,
            week_index=week_index,
            hours_budget=weekly_hours,
            revision_no=0,
            status="dry_run",
            degraded=d["final_degraded"],
            items=d["final_items"],
            overall_reason=d["final_overall_reason"],
        )

    return await _persist_plan(
        session=session,
        learner_id=learner_id,
        week_index=week_index,
        weekly_hours=weekly_hours,
        final_state=final_state,
        cause_type="initial",
        cause_ref=f"run:{run_id}",
        operators=None,
        parent_revision_id=None,
        existing_plan_id=None,
    )


async def patch_existing_plan(
    *,
    session: AsyncSession,
    graph_service: SkillGraphService,
    llm_gateway: LLMGateway,
    embedding_gateway: EmbeddingGateway,
    learner_id: str,
    role_id: str,
    plan_id: str,
    operators: list[dict],
    cause_ref: str = "",
) -> WeeklyPlan:
    """design §16/§20's `patch_existing_plan` -- re-sequence an existing
    plan's items given a closed set of edit operators (design §20.5,
    Reflection's vocabulary). This phase implements the *capability*
    Reflection (Phase 8) will call; it does not itself decide when a patch
    is warranted -- any caller with a valid `plan_id` and `operators` may
    invoke it, same "mechanism now, policy later" split Phase 4 used for
    `LearningObjective` generation ahead of a Planner to consume it.
    """
    repo = PlanningRepository(session)
    plan_row = await repo.get_plan(plan_id)
    if plan_row is None:
        raise UnknownPlanError(f"unknown plan_id {plan_id!r}")
    if plan_row.learner_id != learner_id:
        raise UnknownPlanError("plan does not belong to this learner")
    if plan_row.current_revision_id is None:
        raise UnknownPlanError(f"plan {plan_id!r} has no revisions to patch")

    existing_rows = await repo.list_items_for_revision(plan_row.current_revision_id)
    existing_items = [
        {
            "item_id": r.item_id,
            "type": r.type,
            "objective_id": r.objective_id,
            "skill_id": r.skill_id,
            "resource_id": r.resource_id,
            "practice_item_ids": r.practice_item_ids,
            "est_minutes": r.est_minutes,
            "difficulty": r.difficulty,
            "day_slot": r.day_slot,
            "depends_on": r.depends_on,
        }
        for r in existing_rows
    ]

    hours_budget_minutes = effective_budget_minutes(plan_row.hours_budget)
    final_state, run_id = await _run_graph(
        session=session,
        graph_service=graph_service,
        llm_gateway=llm_gateway,
        embedding_gateway=embedding_gateway,
        learner_id=learner_id,
        role_id=role_id,
        hours_budget_minutes=hours_budget_minutes,
        mode="patch",
        existing_items=existing_items,
        operators=operators,
        modality_order=None,
        language="",
        session_cap_minutes=DEFAULT_SESSION_CAP_MINUTES,
        new_skill_cap=NEW_SKILL_CONCURRENCY_CAP,
    )

    return await _persist_plan(
        session=session,
        learner_id=learner_id,
        week_index=plan_row.week_index,
        weekly_hours=plan_row.hours_budget,
        final_state=final_state,
        cause_type="patch",
        cause_ref=cause_ref or f"run:{run_id}",
        operators=operators,
        parent_revision_id=plan_row.current_revision_id,
        existing_plan_id=plan_id,
    )
