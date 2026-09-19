"""Planner endpoints (design §27): `POST /api/learners/me/plans`,
`GET /api/learners/me/plans/current`. `learner_id` is always resolved from
the session (`get_current_learner_id`, ARCHITECTURE_CONTRACTS.md §7) --
never accepted from the request body. State-changing per
ARCHITECTURE_CONTRACTS.md §8 -- goes through the G2 Planning LangGraph run
(`app/planning/service.py` -> `app/orchestration/graphs.py`), never a bare
CRUD write.

`patch_existing_plan` (design §16/§20) is deliberately **not** exposed here
-- design §27's endpoint table has no row for it (Reflection,
`app/reflection/service.py`, decides *when* a patch is warranted and applies
its own operator pipeline directly, not via `patch_existing_plan`; see that
module's docstring). This phase (Phase 9) *does* add the one-click Revert
surface design §20.7 calls for, since that is genuinely a learner-initiated
action, not something Reflection itself decides.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_learner_id, get_skill_graph_service
from app.db.session import get_session
from app.gateway.embedding_gateway import get_embedding_gateway
from app.gateway.llm_gateway import LLMGateway
from app.graph.queries import SkillGraphService, UnknownRoleError
from app.planning.service import create_plan
from app.reflection.service import UnknownRevisionError, revert_to_previous_revision
from app.repositories.planning_repository import PlanningRepository
from app.repositories.profiling_repository import ProfilingRepository
from app.schemas.common import PlanItem, PlanItemReason
from app.schemas.common import WeeklyPlan as WeeklyPlanOut
from app.schemas.planning import CreatePlanRequest

router = APIRouter(prefix="/learners", tags=["plans"])


@router.post("/me/plans", response_model=WeeklyPlanOut)
async def create_plan_route(
    body: CreatePlanRequest,
    learner_id: str = Depends(get_current_learner_id),
    session: AsyncSession = Depends(get_session),
    graph_service: SkillGraphService = Depends(get_skill_graph_service),
) -> WeeklyPlanOut:
    profile = await ProfilingRepository(session).get_learner_profile(learner_id)
    # get_current_learner_id already guarantees a profile exists (it resolves
    # learner_id FROM the profile), so this is just the type checker's None.
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No learner profile yet")

    weekly_hours = body.hours if body.hours is not None else profile.weekly_hours
    prefs = profile.preferences or {}

    try:
        plan = await create_plan(
            session=session,
            graph_service=graph_service,
            llm_gateway=LLMGateway(),
            embedding_gateway=get_embedding_gateway(),
            learner_id=learner_id,
            role_id=profile.target_role_id,
            week_index=body.week_index,
            weekly_hours=weekly_hours,
            modality_order=prefs.get("modality_order"),
            language=prefs.get("language", ""),
            session_cap_minutes=prefs.get("session_length_min") or 45,
            dry_run=body.dry_run,
        )
    except UnknownRoleError as exc:
        # ARCHITECTURE_CONTRACTS.md §5: "role not supported", never invent a graph.
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="role not supported") from exc

    if not body.dry_run:
        await session.commit()
    return plan


@router.get("/me/plans/current", response_model=WeeklyPlanOut)
async def get_current_plan_route(
    learner_id: str = Depends(get_current_learner_id),
    session: AsyncSession = Depends(get_session),
) -> WeeklyPlanOut:
    repo = PlanningRepository(session)
    plan_row = await repo.get_current_plan_for_learner(learner_id)
    if plan_row is None or plan_row.current_revision_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No plan yet")

    revision = await repo.get_revision(plan_row.current_revision_id)
    item_rows = await repo.list_items_for_revision(plan_row.current_revision_id)
    items = [
        PlanItem(
            item_id=r.item_id,
            type=r.type,
            objective_id=r.objective_id,
            skill_id=r.skill_id,
            resource_id=r.resource_id,
            practice_item_ids=r.practice_item_ids,
            est_minutes=r.est_minutes,
            difficulty=r.difficulty,
            day_slot=r.day_slot,
            depends_on=r.depends_on,
            reason=PlanItemReason(**r.reason) if r.reason else PlanItemReason(),
            status=r.status,
        )
        for r in item_rows
    ]

    return WeeklyPlanOut(
        plan_id=plan_row.plan_id,
        learner_id=learner_id,
        week_index=plan_row.week_index,
        hours_budget=plan_row.hours_budget,
        revision_no=revision.revision_no if revision else 1,
        status=plan_row.status,
        degraded=revision.degraded if revision else False,
        items=items,
        overall_reason=revision.overall_reason if revision else "",
    )


@router.post("/me/plans/{plan_id}/revisions/{revision_id}/revert", response_model=WeeklyPlanOut)
async def revert_plan_revision_route(
    plan_id: str,
    revision_id: str,
    learner_id: str = Depends(get_current_learner_id),
    session: AsyncSession = Depends(get_session),
) -> WeeklyPlanOut:
    """design §20.7: "One-click Revert creates a new revision that restores
    the prior content." Only the plan's *current* revision may be reverted
    (see `app/reflection/service.py::revert_to_previous_revision`)."""
    try:
        plan = await revert_to_previous_revision(session=session, learner_id=learner_id, plan_id=plan_id, revision_id=revision_id)
    except UnknownRevisionError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    await session.commit()
    return plan
