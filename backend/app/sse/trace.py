"""Trace Emitter + SSE broadcast.

Design §7 (Trace Emitter), §31 (Observability): every node wraps execution in
a trace step, writing an AgentStep row (added when AgentRun/AgentStep tables
land, Phase 8/10) and emitting an SSE event. Phase 1 provides the in-process
event bus and the SSE endpoint plumbing; DB persistence of steps is added once
a graph run actually produces steps worth persisting.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
from contextlib import asynccontextmanager
from uuid import uuid4

from app.schemas.envelope import TraceEvent


class TraceBus:
    """Per-run_id fan-out of trace events to any connected SSE clients."""

    def __init__(self) -> None:
        self._queues: dict[str, list[asyncio.Queue[TraceEvent]]] = defaultdict(list)

    def subscribe(self, run_id: str) -> asyncio.Queue[TraceEvent]:
        queue: asyncio.Queue[TraceEvent] = asyncio.Queue()
        self._queues[run_id].append(queue)
        return queue

    def unsubscribe(self, run_id: str, queue: asyncio.Queue[TraceEvent]) -> None:
        if queue in self._queues.get(run_id, []):
            self._queues[run_id].remove(queue)
        if not self._queues.get(run_id):
            self._queues.pop(run_id, None)

    async def publish(self, event: TraceEvent) -> None:
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
