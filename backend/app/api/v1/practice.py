"""Practice & Assessment endpoints (design §27): `POST /api/learners/me/practice`,
`POST /api/practice/{set_id}/submit`. `learner_id` is always resolved from
the session (`get_current_learner_id`, ARCHITECTURE_CONTRACTS.md §7) --
never accepted from the request body. Goes through the deterministic
`app/assessment/service.py` orchestration (grade -> update mastery ->
detect struggle -> deterministic remediation), design §9.5's G3
Evidence-Response scoped to this phase -- see that module's docstring.

Two different path prefixes (`/learners/me/practice` vs `/practice/{id}`),
matching design §27's table exactly -- this router intentionally has no
single `APIRouter(prefix=...)`, unlike every other router in this project.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_learner_id, get_skill_graph_service
from app.assessment.resolution import RemediationOutcome
from app.assessment.service import SubmittedAnswer, UnknownPracticeSessionError, create_practice_session, submit_practice_set
from app.db.session import get_session
from app.gateway.llm_gateway import LLMGateway
from app.graph.queries import SkillGraphService, UnknownSkillError
from app.repositories.catalog_repository import CatalogRepository
from app.schemas.assessment import (
    CreatePracticeSetRequest,
    PracticeItemOut,
    PracticeSetOut,
    RemediationOut,
    SubmitPracticeRequest,
    SubmitPracticeResponse,
)
from app.schemas.common import AssessmentItemResult, AssessmentResult, StruggleSignal as StruggleSignalOut

router = APIRouter(tags=["practice"])


@router.post("/learners/me/practice", response_model=PracticeSetOut)
async def create_practice_set_route(
    body: CreatePracticeSetRequest,
    learner_id: str = Depends(get_current_learner_id),
    session: AsyncSession = Depends(get_session),
    graph_service: SkillGraphService = Depends(get_skill_graph_service),
) -> PracticeSetOut:
    try:
        practice_session = await create_practice_session(
            session=session,
            graph=graph_service,
            llm_gateway=LLMGateway(),
            learner_id=learner_id,
            skill_id=body.skill_id,
            purpose=body.purpose,
        )
    except UnknownSkillError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="unknown skill_id") from exc

    catalog = CatalogRepository(session)
    items = await catalog.get_practice_items_by_ids(practice_session.item_ids)
    items_by_id = {i.item_id: i for i in items}
    await session.commit()

    return PracticeSetOut(
        set_id=practice_session.set_id,
        skill_id=practice_session.skill_id,
        purpose=practice_session.purpose,
        items=[
            PracticeItemOut(
                item_id=item_id,
                skill_id=items_by_id[item_id].skill_id,
                difficulty=items_by_id[item_id].difficulty,
                stem=items_by_id[item_id].stem,
                options=[o["text"] for o in items_by_id[item_id].options],
            )
            for item_id in practice_session.item_ids
            if item_id in items_by_id
        ],
    )


@router.post("/practice/{set_id}/submit", response_model=SubmitPracticeResponse)
async def submit_practice_set_route(
    set_id: str,
    body: SubmitPracticeRequest,
    learner_id: str = Depends(get_current_learner_id),
    session: AsyncSession = Depends(get_session),
    graph_service: SkillGraphService = Depends(get_skill_graph_service),
) -> SubmitPracticeResponse:
    try:
        outcome = await submit_practice_set(
            session=session,
            graph=graph_service,
            llm_gateway=LLMGateway(),
            learner_id=learner_id,
            set_id=set_id,
            answers=[SubmittedAnswer(item_id=a.item_id, chosen_option=a.chosen_option, time_sec=a.time_sec) for a in body.answers],
            self_reported_overload=body.self_reported_overload,
            planned_vs_actual_ratio=body.planned_vs_actual_ratio,
            completion_rate=body.completion_rate,
            retries_trend_rising=body.retries_trend_rising,
            new_skills_active=body.new_skills_active,
        )
    except UnknownPracticeSessionError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    await session.commit()

    remediation_out: RemediationOut | None = None
    if outcome.remediation is not None:
        r: RemediationOutcome = outcome.remediation
        remediation_out = RemediationOut(
            misconception_id=r.learner_misconception.misconception_id,
            status=r.learner_misconception.status,
            started=r.started,
            skip_reason=r.skip_reason,
            remediation_resource_ids=r.remediation_resource_ids,
            plan_revision_id=r.plan_revision_id,
        )

    return SubmitPracticeResponse(
        result=AssessmentResult(
            assessment_id=outcome.assessment_id,
            learner_id=learner_id,
            skill_id=outcome.skill_id,
            purpose=outcome.purpose,
            items=[AssessmentItemResult(**item) for item in outcome.items],
            score=outcome.score,
            submitted_at=outcome.submitted_at,
        ),
        signals=[
            StruggleSignalOut(
                signal_id=s.signal_id,
                learner_id=learner_id,
                signal_class=s.signal_class,
                skill_id=s.skill_id,
                confidence=s.confidence,
                evidence_ids=s.evidence_ids,
                counts=s.counts,
                thresholds_used=s.thresholds_used,
            )
            for s in outcome.signals
        ],
        remediation=remediation_out,
    )
