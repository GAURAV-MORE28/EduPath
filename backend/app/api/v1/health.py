"""Health endpoint.

Reports process liveness, DB connectivity, and whether the LangGraph
orchestration framework compiled at startup — the three things design §35
(Deployment Architecture) says must fail fast at startup rather than silently
degrade.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.orchestration.graphs import build_bootstrap_graph

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(session: AsyncSession = Depends(get_session)) -> dict:
    db_ok = True
    db_error: str | None = None
    try:
        await session.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 - reported in the response, not swallowed
        db_ok = False
        db_error = str(exc)

    graph_ok = True
    graph_error: str | None = None
    try:
        build_bootstrap_graph()
    except Exception as exc:  # noqa: BLE001
        graph_ok = False
        graph_error = str(exc)

    status = "ok" if db_ok and graph_ok else "degraded"
    return {
        "status": status,
        "database": {"ok": db_ok, "error": db_error},
        "orchestration": {"ok": graph_ok, "error": graph_error},
    }
