"""DEMO_MODE endpoints (design §27 "demo seed", §38.3 reliability plan).

`GET  /api/demo/preflight`         -- the rehearsal checklist (always available; no learner data).
`POST /api/demo/seed`              -- (re)create the seeded persona for the current session user.
`POST /api/demo/scripted-attempt`  -- submit the scripted wrong answers through the real submit path.

The last two answer 403 unless `DEMO_MODE=true`. They act only on the session's own learner
(`learner_id` is never taken from the body, ARCHITECTURE_CONTRACTS.md §7).
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_learner_id, get_current_user_id, get_skill_graph_service
from app.api.v1.practice import build_reflection_out
from app.db.session import get_session
from app.demo.service import (
    DemoDisabledError,
    DemoScenarioError,
    load_scenario,
    preflight,
    run_scripted_attempt,
    seed_demo_learner,
)
from app.graph.queries import SkillGraphService
from app.schemas.assessment import ReflectionOut

router = APIRouter(prefix="/demo", tags=["demo"])


class DemoSeedResponse(BaseModel):
    learner_id: str
    role_id: str
    scenario_id: str
    claims_extracted: int
    claims_confirmed: int
    evidence_created: int
    seeded_skills: list[str] = Field(default_factory=list)
    plan_id: str | None
    plan_item_count: int
    tutor_demo_questions: list[str] = Field(default_factory=list)


class ScriptedAttemptResponse(BaseModel):
    assessment_id: str
    skill_id: str
    score: float
    signal_classes: list[str]
    reflection: ReflectionOut | None


@router.get("/preflight")
async def preflight_route(
    session: AsyncSession = Depends(get_session), graph_service: SkillGraphService = Depends(get_skill_graph_service)
) -> dict[str, Any]:
    return await preflight(session, graph_service)


@router.post("/seed", response_model=DemoSeedResponse)
async def seed_route(
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
    graph_service: SkillGraphService = Depends(get_skill_graph_service),
) -> DemoSeedResponse:
    try:
        result = await seed_demo_learner(session, graph_service, user_id=user_id)
    except DemoDisabledError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return DemoSeedResponse(
        learner_id=result.learner_id,
        role_id=result.role_id,
        scenario_id=result.scenario_id,
        claims_extracted=result.claims_extracted,
        claims_confirmed=result.claims_confirmed,
        evidence_created=len(result.evidence_ids),
        seeded_skills=result.seeded_skills,
        plan_id=result.plan_id,
        plan_item_count=result.plan_item_count,
        tutor_demo_questions=load_scenario().get("tutor_demo_questions", []),
    )


@router.post("/scripted-attempt", response_model=ScriptedAttemptResponse)
async def scripted_attempt_route(
    learner_id: str = Depends(get_current_learner_id),
    session: AsyncSession = Depends(get_session),
    graph_service: SkillGraphService = Depends(get_skill_graph_service),
) -> ScriptedAttemptResponse:
    try:
        outcome = await run_scripted_attempt(session, graph_service, learner_id=learner_id)
    except DemoDisabledError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except DemoScenarioError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return ScriptedAttemptResponse(
        assessment_id=outcome.assessment_id,
        skill_id=outcome.skill_id,
        score=outcome.score,
        signal_classes=sorted({s.signal_class for s in outcome.signals}),
        reflection=build_reflection_out(outcome.reflection) if outcome.reflection is not None else None,
    )
