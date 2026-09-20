"""FastAPI application entrypoint.

Modular monolith (design §6, §35): one FastAPI process hosts the API layer,
the LangGraph orchestrator, agents, and deterministic services.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.config import get_settings
from app.core.errors import register_exception_handlers
from app.logging_config import configure_logging, get_logger
from app.observability.context import RunContext, current_run
from app.observability.store import persist_run
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

        if settings.auto_seed_catalog:
            from app.catalog.bootstrap import ensure_catalog

            async with SessionLocal() as session:
                await ensure_catalog(session)
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
    """Pure-ASGI middleware: opens one `RunContext` per `/api` request (design
    §31 -- every important action gets a run id), copies a valid client
    `X-Run-Id` into it (so the SSE panel the client already subscribed to gets
    the events), echoes the run id back in an `X-Run-Id` response header, and
    persists the run + its steps (`app.observability.store.persist_run`) once
    the response is done. Persistence errors never reach the client."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        client_run_id = None
        for name, value in scope.get("headers", []):
            if name == b"x-run-id":
                candidate = value.decode("latin-1").strip()
                if 8 <= len(candidate) <= 64 and all(c.isalnum() or c == "-" for c in candidate):
                    client_run_id = candidate
                break

        # Health probes and the SSE stream itself are not "actions".
        if not path.startswith("/api") or path == "/api/health" or path.endswith("/events"):
            token = current_run_id.set(client_run_id)
            try:
                await self.app(scope, receive, send)
            finally:
                current_run_id.reset(token)
            return

        ctx = RunContext(
            run_id=client_run_id or str(uuid4()),
            client_supplied=client_run_id is not None,
            method=scope.get("method", ""),
            route=path,
        )
        run_token = current_run.set(ctx)
        id_token = current_run_id.set(client_run_id)
        state = {"status": 0}

        async def send_with_run_id(message) -> None:
            if message["type"] == "http.response.start":
                state["status"] = message["status"]
                headers = list(message.get("headers", []))
                headers.append((b"x-run-id", ctx.run_id.encode("latin-1")))
                message = {**message, "headers": headers}
            await send(message)

        error: str | None = None
        try:
            await self.app(scope, receive, send_with_run_id)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"[:500]
            if not state["status"]:
                state["status"] = 500
            raise
        finally:
            current_run.reset(run_token)
            current_run_id.reset(id_token)
            await persist_run(ctx, http_status=state["status"], error=error)


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
        expose_headers=["X-Run-Id"],
    )

    app.add_middleware(TraceRunMiddleware)

    register_exception_handlers(app)
    app.include_router(api_router, prefix=settings.api_v1_prefix)

    return app


app = create_app()
