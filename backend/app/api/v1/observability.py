"""Observability endpoints (design §27 `GET /runs/{id}`, §31.2 metrics).

`GET /api/runs/{run_id}` -- a persisted run and its steps; only its owner may
read it (a foreign or unknown run is a 404, never a 403, so run ids are not
an existence oracle). `GET /api/learners/me/runs` -- the caller's recent runs.
`GET /api/metrics` -- learner-anonymous aggregates only (latency percentiles,
LLM calls, retries, planner loops, tokens, cost, degraded/failed rates).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user_id
from app.db.session import get_session
from app.observability.store import compute_metrics, get_run_with_steps, list_runs_for_user

router = APIRouter(tags=["observability"])


class RunSummary(BaseModel):
    run_id: str
    learner_id: str | None
    method: str
    route: str
    graph: str
    status: str
    http_status: int
    started_at: datetime
    duration_ms: float
    llm_calls: int
    llm_retries: int
    llm_replays: int
    llm_degraded: int
    tokens_in: int
    tokens_out: int
    cost_usd: float
    planner_loops: int
    retrieval_ms: float
    degraded: bool


class StepOut(BaseModel):
    step_id: str
    run_id: str
    learner_id: str | None
    seq: int
    actor: str
    kind: str
    summary: str
    refs: list[str]
    input_ref: str
    output_ref: str
    decision_id: str | None
    duration_ms: float
    tokens_in: int
    tokens_out: int
    cost_usd: float
    status: str
    created_at: datetime


class RunDetail(RunSummary):
    steps: list[StepOut]


def _summary(run) -> dict[str, Any]:
    return {f: getattr(run, f) for f in RunSummary.model_fields}


@router.get("/runs/{run_id}", response_model=RunDetail)
async def get_run_route(
    run_id: str,
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
) -> RunDetail:
    found = await get_run_with_steps(session, run_id)
    if found is None or found[0].user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown run_id")
    run, steps = found
    return RunDetail(**_summary(run), steps=[StepOut(**{f: getattr(s, f) for f in StepOut.model_fields}) for s in steps])


@router.get("/learners/me/runs", response_model=list[RunSummary])
async def list_my_runs_route(
    limit: int = Query(default=50, ge=1, le=200),
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
) -> list[RunSummary]:
    return [RunSummary(**_summary(r)) for r in await list_runs_for_user(session, user_id, limit=limit)]


@router.get("/metrics")
async def get_metrics_route(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    return await compute_metrics(session)
