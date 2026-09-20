"""FastAPI application entrypoint.

Modular monolith (design §6, §35): one FastAPI process hosts the API layer,
the LangGraph orchestrator, agents, and deterministic services.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.config import get_settings
from app.core.errors import register_exception_handlers
from app.logging_config import configure_logging, get_logger
from app.orchestration.graphs import build_bootstrap_graph
from app.sse.trace import current_run_id

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    settings = get_settings()
    # Fail fast at startup if the orchestration framework doesn't compile
    # (design §30: graph load failure should fail fast, not degrade silently).
    build_bootstrap_graph()

    # Best-effort: load the curated Skill Graph once at startup and cache it
    # on app.state (ARCHITECTURE_CONTRACTS.md §5 "loaded... at process
    # startup"; IMPLEMENTATION_STATE.md's "Known Issues" flagged this as
    # owed to the Gap Engine's first real caller). Not fail-fast, unlike the
    # orchestration graph above: an empty/not-yet-seeded catalog is a normal
    # pre-`seed_catalog.py` state (e.g. a fresh dev DB), not a startup bug --
    # `app.api.deps.get_skill_graph_service` falls back to a per-request load
    # whenever this cache is absent.
    app.state.skill_graph_service = None
    try:
        from app.db.session import SessionLocal
        from app.graph.loader import GraphLoader
        from app.graph.queries import SkillGraphService
        from app.repositories.catalog_repository import CatalogRepository

        async with SessionLocal() as session:
            skill_graph = await GraphLoader(CatalogRepository(session)).load()
        app.state.skill_graph_service = SkillGraphService(skill_graph)
        logger.info("edupath.startup.skill_graph_loaded", graph_version=skill_graph.graph_version)
    except Exception:  # noqa: BLE001 -- degrade, never block startup on this
        logger.warning("edupath.startup.skill_graph_load_failed", exc_info=True)

    logger.info("edupath.startup", env=settings.env, demo_mode=settings.demo_mode)
    yield
    logger.info("edupath.shutdown")


class TraceRunMiddleware:
    """Pure-ASGI middleware: copies a valid `X-Run-Id` request header into the
    `current_run_id` context var so services can `emit()` trace events for the
    run the client is already subscribed to."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        run_id = None
        for name, value in scope.get("headers", []):
            if name == b"x-run-id":
                candidate = value.decode("latin-1").strip()
                if 8 <= len(candidate) <= 64 and all(c.isalnum() or c == "-" for c in candidate):
                    run_id = candidate
                break
        token = current_run_id.set(run_id)
        try:
            await self.app(scope, receive, send)
        finally:
            current_run_id.reset(token)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="EduPath API",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.add_middleware(TraceRunMiddleware)

    register_exception_handlers(app)
    app.include_router(api_router, prefix=settings.api_v1_prefix)

    return app


app = create_app()
