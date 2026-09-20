"""Trace Emitter + SSE broadcast.

Design §7 (Trace Emitter), §31 (Observability): every node wraps execution in
a trace step, writing an AgentStep row (added when AgentRun/AgentStep tables
land, Phase 8/10) and emitting an SSE event. Phase 1 provides the in-process
event bus and the SSE endpoint plumbing; DB persistence of steps is added once
a graph run actually produces steps worth persisting.
"""
from __future__ import annotations

import asyncio
from collections import OrderedDict, defaultdict
from contextlib import asynccontextmanager
from contextvars import ContextVar
from uuid import uuid4

from app.schemas.envelope import TraceEvent


# Bounded replay so a client that opens the SSE stream slightly after the
# work started (or after it finished) still sees the run's real events.
_MAX_REPLAY_RUNS = 200
_MAX_EVENTS_PER_RUN = 200

# The request-scoped run id the client asked to trace (`X-Run-Id` header,
# set by `TraceRunMiddleware` in app/main.py). Services call `emit()` without
# threading a run id through every signature; with no id set, emit is a no-op.
current_run_id: ContextVar[str | None] = ContextVar("edupath_current_run_id", default=None)


class TraceBus:
    """Per-run_id fan-out of trace events to any connected SSE clients, with
    a small bounded history replayed to late subscribers."""

    def __init__(self) -> None:
        self._queues: dict[str, list[asyncio.Queue[TraceEvent]]] = defaultdict(list)
        self._history: OrderedDict[str, list[TraceEvent]] = OrderedDict()

    def subscribe(self, run_id: str) -> asyncio.Queue[TraceEvent]:
        queue: asyncio.Queue[TraceEvent] = asyncio.Queue()
        for event in self._history.get(run_id, []):
            queue.put_nowait(event)
        self._queues[run_id].append(queue)
        return queue

    def unsubscribe(self, run_id: str, queue: asyncio.Queue[TraceEvent]) -> None:
        if queue in self._queues.get(run_id, []):
            self._queues[run_id].remove(queue)
        if not self._queues.get(run_id):
            self._queues.pop(run_id, None)

    async def publish(self, event: TraceEvent) -> None:
        events = self._history.setdefault(event.run_id, [])
        self._history.move_to_end(event.run_id)
        if len(events) < _MAX_EVENTS_PER_RUN:
            events.append(event)
        while len(self._history) > _MAX_REPLAY_RUNS:
            self._history.popitem(last=False)
        for queue in self._queues.get(event.run_id, []):
            await queue.put(event)


trace_bus = TraceBus()


@asynccontextmanager
async def step(run_id: str, actor: str, kind: str, summary: str, refs: list[str] | None = None):
    """Context manager used by orchestration nodes/services to emit a trace
    event around a unit of work. Usage:

        async with trace.step(run_id, "Gap Engine", "decision", "computed gaps") as ev:
            ...
    """
    event = TraceEvent(
        run_id=run_id,
        step_id=str(uuid4()),
        agent_or_service=actor,
        kind=kind,
        summary=summary,
        refs=refs or [],
    )
    try:
        yield event
    finally:
        await trace_bus.publish(event)


async def emit(actor: str, kind: str, summary: str, refs: list[str] | None = None) -> None:
    """Publish one real trace event for the request's run, if the client asked
    to trace it (`X-Run-Id`). Never raises: tracing must not break the work it
    describes (ARCHITECTURE_CONTRACTS.md §11: degrade, never hard-fail)."""
    run_id = current_run_id.get()
    if run_id is None:
        return
    try:
        await trace_bus.publish(
            TraceEvent(run_id=run_id, step_id=str(uuid4()), agent_or_service=actor, kind=kind, summary=summary, refs=refs or [])
        )
    except Exception:  # noqa: BLE001
        pass
