"""SSE trace stream for a run (design §27: `GET /api/runs/{run_id}/events`).

Phase 1 wires the SSE transport against the in-process TraceBus so the
frontend's trace panel has a real endpoint to connect to from day one. No
graph produces events yet (that starts in Phase 2), so this stream simply
stays open and forwards whatever is published for that run_id.
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from app.sse.trace import trace_bus

router = APIRouter(prefix="/runs", tags=["runs"])


@router.get("/{run_id}/events")
async def stream_run_events(run_id: str, request: Request) -> EventSourceResponse:
    queue = trace_bus.subscribe(run_id)

    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield {"event": event.kind, "data": event.model_dump_json()}
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": "{}"}
        finally:
            trace_bus.unsubscribe(run_id, queue)

    return EventSourceResponse(event_generator())
