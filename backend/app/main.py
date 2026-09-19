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

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    settings = get_settings()
    # Fail fast at startup if the orchestration framework doesn't compile
    # (design §30: graph load failure should fail fast, not degrade silently).
    build_bootstrap_graph()
    logger.info("edupath.startup", env=settings.env, demo_mode=settings.demo_mode)
    yield
    logger.info("edupath.shutdown")


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

    register_exception_handlers(app)
    app.include_router(api_router, prefix=settings.api_v1_prefix)

    return app


app = create_app()
