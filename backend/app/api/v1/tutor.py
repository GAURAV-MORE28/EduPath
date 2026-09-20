"""Tutor / Provenance endpoints (design §27): `POST /api/learners/me/chat`,
`GET /api/learners/me/progress`, `GET /api/decisions/{id}`. `learner_id` is
always resolved from the session (`get_current_learner_id`,
ARCHITECTURE_CONTRACTS.md §7) -- never accepted from the request body or
path.

`POST /api/learners/me/chat` is a plain JSON request/response here, not the
SSE stream design §27 describes -- the Phase 10 brief asks for the grounded
answer + citation verification + conservative fallback, not a streaming
transport; `app/sse/trace.py`'s `TraceBus` already exists for a later phase
to wire this onto once there is a UI that needs token-by-token streaming.
The response is the same complete, citation-verified answer a stream would
have ended with.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_learner_id, get_skill_graph_service
from app.db.session import get_session
from app.gateway.llm_gateway import LLMGateway
from app.graph.queries import SkillGraphService, UnknownRoleError
from app.repositories.reflection_repository import ReflectionRepository
from app.schemas.common import ProgressActivityEntry, ProgressReport, ProgressSkillEntry, StruggleAreaEntry
from app.schemas.tutor import ChatRequest, ChatResponse, DecisionRecordOut
from app.tutor.report_builder import compute_progress_report
from app.tutor.service import NoLearnerProfileError, build_tutor_context, narrate_progress, run_chat

router = APIRouter(tags=["tutor"])


@router.post("/learners/me/chat", response_model=ChatResponse)
async def chat_route(
    body: ChatRequest,
    learner_id: str = Depends(get_current_learner_id),
    session: AsyncSession = Depends(get_session),
    graph_service: SkillGraphService = Depends(get_skill_graph_service),
) -> ChatResponse:
    try:
        answer = await run_chat(
            session=session,
            graph=graph_service,
            llm_gateway=LLMGateway(),
            learner_id=learner_id,
            message=body.message,
            skill_id_hint=body.skill_id_hint,
            decision_id_hint=body.decision_id_hint,
        )
    except NoLearnerProfileError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No learner profile yet") from exc
    except UnknownRoleError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="role not supported") from exc

    return ChatResponse(
        answer=answer.answer, citations=answer.citations, degraded=answer.degraded, conservative=answer.conservative
    )


@router.get("/learners/me/progress", response_model=ProgressReport)
async def get_progress_route(
    period: str = "all_time",
    learner_id: str = Depends(get_current_learner_id),
    session: AsyncSession = Depends(get_session),
    graph_service: SkillGraphService = Depends(get_skill_graph_service),
) -> ProgressReport:
    try:
        ctx = await build_tutor_context(session, graph_service, learner_id)
    except NoLearnerProfileError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No learner profile yet") from exc
    except UnknownRoleError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="role not supported") from exc

    report = await compute_progress_report(ctx, period=period)
    narrative, _degraded = await narrate_progress(LLMGateway(), report)

    return ProgressReport(
        learner_id=report.learner_id,
        role_id=report.role_id,
        period=report.period,
        graph_version=report.graph_version,
        acquired=[ProgressSkillEntry(**vars(s)) for s in report.acquired],
        in_progress=[ProgressSkillEntry(**vars(s)) for s in report.in_progress],
        remaining_gaps=[
            {
                "skill_id": g.skill_id, "label": g.label, "status": g.status, "gap_type": g.gap_type,
                "required_level": g.required_level, "current_level": g.current_level, "blocked_by": g.blocked_by,
                "root_of": g.root_of, "priority": g.priority, "ordering_layer": g.ordering_layer,
                "evidence_ids": g.evidence_ids, "audit_flags": g.audit_flags,
            }
            for g in report.remaining_gaps
        ],
        struggle_areas=[StruggleAreaEntry(**vars(sa)) for sa in report.struggle_areas],
        completed_work=[ProgressActivityEntry(**vars(a)) for a in report.completed_work],
        next_steps=[ProgressActivityEntry(**vars(a)) for a in report.next_steps],
        narrative=narrative,
    )


@router.get("/decisions/{decision_id}", response_model=DecisionRecordOut)
async def get_decision_route(
    decision_id: str,
    learner_id: str = Depends(get_current_learner_id),
    session: AsyncSession = Depends(get_session),
) -> DecisionRecordOut:
    record = await ReflectionRepository(session).get_decision_record(learner_id, decision_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown decision_id")

    return DecisionRecordOut(
        decision_id=record.decision_id, learner_id=record.learner_id, type=record.type, inputs=record.inputs,
        evidence_ids=record.evidence_ids, graph_paths=record.graph_paths, rules_fired=record.rules_fired,
        scores=record.scores, graph_version=record.graph_version, output_ref=record.output_ref,
    )
