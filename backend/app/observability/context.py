"""Request-scoped run context: the in-memory half of the persisted trace.

design §31.2 / ARCHITECTURE_CONTRACTS.md §8: every important action has a
run id, step ids, an actor, input/output *references*, an optional decision
record, a duration, token/cost where a provider reports them, and a status.

`TraceRunMiddleware` (app/main.py) opens one `RunContext` per API request and
persists it (`app.observability.store.persist_run`) when the response is done.
Services never touch this module's persistence: they call `app.sse.trace.emit`
/ `span` (which append a step here) and the gateway calls the `note_*` helpers.
Every helper is a silent no-op outside a request (scripts, unit tests), and
none of them can raise -- tracing must never break the work it describes
(ARCHITECTURE_CONTRACTS.md §11).
"""
from __future__ import annotations

import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4


@dataclass
class StepRecord:
    step_id: str
    seq: int
    actor: str
    kind: str
    summary: str
    refs: list[str]
    input_ref: str = ""
    output_ref: str = ""
    decision_id: str | None = None
    duration_ms: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    status: str = "ok"  # ok | degraded | error
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class RunContext:
    run_id: str
    client_supplied: bool
    method: str = ""
    route: str = ""
    user_id: str | None = None
    learner_id: str | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    t0: float = field(default_factory=time.perf_counter)
    steps: list[StepRecord] = field(default_factory=list)
    llm_calls: int = 0
    llm_retries: int = 0
    llm_replays: int = 0
    llm_degraded: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    planner_loops: int = 0
    retrieval_ms: float = 0.0
    _last_mark: float = field(default_factory=time.perf_counter)

    def add_step(
        self,
        actor: str,
        kind: str,
        summary: str,
        refs: list[str] | None = None,
        *,
        duration_ms: float | None = None,
        status: str | None = None,
        input_ref: str = "",
        output_ref: str = "",
        decision_id: str | None = None,
        tokens_in: int = 0,
        tokens_out: int = 0,
        cost_usd: float = 0.0,
    ) -> StepRecord:
        now = time.perf_counter()
        if duration_ms is None:
            # Steps emitted after their work finished report the wall time since the
            # previous step (or the request start): honest elapsed time, not a guess.
            duration_ms = (now - self._last_mark) * 1000.0
        self._last_mark = now
        if status is None:
            status = "degraded" if kind == "degraded" else "error" if kind == "error" else "ok"
        step = StepRecord(
            step_id=str(uuid4()),
            seq=len(self.steps) + 1,
            actor=actor,
            kind=kind,
            summary=summary,
            refs=list(refs or []),
            input_ref=input_ref,
            output_ref=output_ref,
            decision_id=decision_id,
            duration_ms=round(duration_ms, 3),
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost_usd,
            status=status,
        )
        self.steps.append(step)
        return step

    @property
    def degraded(self) -> bool:
        return any(s.kind == "degraded" or s.status == "degraded" for s in self.steps if s.actor != "LLM Gateway")


current_run: ContextVar[RunContext | None] = ContextVar("edupath_current_run", default=None)


def get_run() -> RunContext | None:
    return current_run.get()


def bind_identity(*, user_id: str | None = None, learner_id: str | None = None) -> None:
    ctx = current_run.get()
    if ctx is None:
        return
    if user_id is not None:
        ctx.user_id = user_id
    if learner_id is not None:
        ctx.learner_id = learner_id


def note_llm_call(
    *,
    tokens_in: int = 0,
    tokens_out: int = 0,
    cost_usd: float = 0.0,
    replayed: bool = False,
    degraded: bool = False,
) -> None:
    ctx = current_run.get()
    if ctx is None:
        return
    ctx.llm_calls += 1
    ctx.tokens_in += tokens_in
    ctx.tokens_out += tokens_out
    ctx.cost_usd += cost_usd
    if replayed:
        ctx.llm_replays += 1
    if degraded:
        ctx.llm_degraded += 1


def note_retry() -> None:
    """One agent-level retry (schema/ID validation failure -> re-ask, max 2)."""
    ctx = current_run.get()
    if ctx is not None:
        ctx.llm_retries += 1


def note_planner_loop() -> None:
    ctx = current_run.get()
    if ctx is not None:
        ctx.planner_loops += 1


def note_retrieval(duration_ms: float) -> None:
    ctx = current_run.get()
    if ctx is not None:
        ctx.retrieval_ms += duration_ms


def graph_for_route(method: str, path: str) -> str:
    """Which design §9 graph / area a request belongs to (for grouping metrics)."""
    if path.startswith("/api/demo"):
        return "demo"
    if "/me/plans" in path:
        return "planning"
    if "/practice" in path:
        return "assessment"
    if path.endswith("/chat") or path.endswith("/progress") or "/decisions/" in path:
        return "tutor"
    if path == "/api/learners" or "/me/documents" in path or "/me/claims" in path:
        return "onboarding"
    return "api"
