"""Persistence and aggregation for the run/step trace (design §28, §31).

`persist_run` is called by `TraceRunMiddleware` after each response; it opens
its own short session (never the request's -- the request may have rolled
back) and swallows every error: a failed audit write must not fail the
request that was already answered. `compute_metrics` powers `GET /api/metrics`
and the benchmark script.
"""
from __future__ import annotations

import math
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentRun, AgentStep
from app.logging_config import get_logger
from app.observability.context import RunContext, graph_for_route

logger = get_logger(__name__)


def _should_persist(ctx: RunContext) -> bool:
    """Persist every state-changing request and any request that produced trace
    steps or LLM calls; skip bare GET reads (views, health polling) so the
    audit table records actions, not page loads."""
    if ctx.method != "GET":
        return True
    return bool(ctx.steps) or ctx.llm_calls > 0 or ctx.client_supplied


async def persist_run(ctx: RunContext, *, http_status: int, error: str | None) -> None:
    if not _should_persist(ctx):
        return
    try:
        from app.db.session import SessionLocal

        async with SessionLocal() as session:
            run_id = ctx.run_id
            if await session.get(AgentRun, run_id) is not None:
                # A client reused an X-Run-Id: keep both audit records.
                run_id = f"{run_id[:56]}~{uuid.uuid4().hex[:6]}"
            failed = http_status >= 500 or error is not None
            session.add(
                AgentRun(
                    run_id=run_id,
                    user_id=ctx.user_id,
                    learner_id=ctx.learner_id,
                    method=ctx.method[:8],
                    route=ctx.route[:200],
                    graph=graph_for_route(ctx.method, ctx.route),
                    status="failed" if failed else "degraded" if ctx.degraded else "completed",
                    http_status=http_status,
                    started_at=ctx.started_at,
                    ended_at=datetime.now(timezone.utc),
                    duration_ms=round(_elapsed_ms(ctx), 3),
                    llm_calls=ctx.llm_calls,
                    llm_retries=ctx.llm_retries,
                    llm_replays=ctx.llm_replays,
                    llm_degraded=ctx.llm_degraded,
                    tokens_in=ctx.tokens_in,
                    tokens_out=ctx.tokens_out,
                    cost_usd=ctx.cost_usd,
                    planner_loops=ctx.planner_loops,
                    retrieval_ms=round(ctx.retrieval_ms, 3),
                    degraded=ctx.degraded,
                    error=error,
                )
            )
            await session.flush()  # the run row must exist before its steps (FK)
            for step in ctx.steps:
                session.add(
                    AgentStep(
                        step_id=step.step_id,
                        run_id=run_id,
                        learner_id=ctx.learner_id,
                        seq=step.seq,
                        actor=step.actor[:64],
                        kind=step.kind[:24],
                        summary=step.summary,
                        refs=step.refs,
                        input_ref=step.input_ref[:200],
                        output_ref=step.output_ref[:200],
                        decision_id=step.decision_id,
                        duration_ms=step.duration_ms,
                        tokens_in=step.tokens_in,
                        tokens_out=step.tokens_out,
                        cost_usd=step.cost_usd,
                        status=step.status,
                        created_at=step.created_at,
                    )
                )
            await session.commit()
    except Exception:  # noqa: BLE001 -- an audit-write failure must never fail the request
        logger.warning("edupath.observability.persist_failed", run_id=ctx.run_id, exc_info=True)


def _elapsed_ms(ctx: RunContext) -> float:
    return (time.perf_counter() - ctx.t0) * 1000.0


async def get_run_with_steps(session: AsyncSession, run_id: str) -> tuple[AgentRun, list[AgentStep]] | None:
    run = await session.get(AgentRun, run_id)
    if run is None:
        return None
    steps = (await session.execute(select(AgentStep).where(AgentStep.run_id == run_id).order_by(AgentStep.seq))).scalars().all()
    return run, list(steps)


async def list_runs_for_user(session: AsyncSession, user_id: str, *, limit: int = 50) -> list[AgentRun]:
    stmt = select(AgentRun).where(AgentRun.user_id == user_id).order_by(AgentRun.started_at.desc()).limit(limit)
    return list((await session.execute(stmt)).scalars().all())


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(0, min(len(ordered) - 1, math.ceil(pct / 100.0 * len(ordered)) - 1))
    return round(ordered[rank], 3)


async def compute_metrics(session: AsyncSession, *, limit: int = 2000) -> dict[str, Any]:
    """Aggregate, learner-anonymous performance/observability metrics over the
    most recent `limit` runs (design §31.2's metrics list)."""
    runs = list((await session.execute(select(AgentRun).order_by(AgentRun.started_at.desc()).limit(limit))).scalars().all())
    by_graph: dict[str, list[AgentRun]] = {}
    for r in runs:
        by_graph.setdefault(r.graph, []).append(r)

    def summarize(group: list[AgentRun]) -> dict[str, Any]:
        n = len(group)
        durations = [r.duration_ms for r in group]
        return {
            "runs": n,
            "latency_ms": {
                "p50": _percentile(durations, 50),
                "p95": _percentile(durations, 95),
                "max": round(max(durations), 3) if durations else 0.0,
                "mean": round(sum(durations) / n, 3) if n else 0.0,
            },
            "llm_calls": sum(r.llm_calls for r in group),
            "llm_retries": sum(r.llm_retries for r in group),
            "llm_replays": sum(r.llm_replays for r in group),
            "llm_degraded_calls": sum(r.llm_degraded for r in group),
            "planner_loops": sum(r.planner_loops for r in group),
            "tokens_in": sum(r.tokens_in for r in group),
            "tokens_out": sum(r.tokens_out for r in group),
            "cost_usd": round(sum(r.cost_usd for r in group), 6),
            "retrieval_ms_total": round(sum(r.retrieval_ms for r in group), 3),
            "degraded_run_rate": round(sum(1 for r in group if r.degraded) / n, 4) if n else 0.0,
            "failed_run_rate": round(sum(1 for r in group if r.status == "failed") / n, 4) if n else 0.0,
        }

    return {
        "window_runs": len(runs),
        "overall": summarize(runs),
        "by_graph": {graph: summarize(group) for graph, group in sorted(by_graph.items())},
    }
