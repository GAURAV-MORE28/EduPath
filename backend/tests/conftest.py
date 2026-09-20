"""Shared test fixtures.

Uses an in-memory SQLite engine for the smoke/DB tests so the suite runs
without a live Postgres instance. Real Postgres-only features (pgvector,
JSONB-specific queries) are exercised against Postgres once the phase that
needs them lands; Phase 1 only needs to prove connectivity + migrations.
"""
import os
import tempfile

# The suite must be deterministic and offline no matter what a developer's `.env` holds (real provider
# keys, DEMO_MODE, ...): environment variables outrank the dotenv file, so pin every external service off.
for _name, _value in {
    "LLM_PROVIDER": "none", "EMBEDDING_PROVIDER": "none", "VLM_PROVIDER": "none", "WEB_SEARCH_PROVIDER": "none",
    "LLM_API_KEY": "", "HF_TOKEN": "", "TAVILY_API_KEY": "", "GITHUB_TOKEN": "",
    "DEMO_MODE": "false", "REPLAY_MODE": "false", "LLM_RECORD": "false",
}.items():
    os.environ[_name] = _value
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
# Document uploads (Phase 2 profiling) would otherwise land under the default
# ./storage/documents relative to the test run's cwd -- redirect to a
# session-scoped temp dir so tests never write into the repo tree.
os.environ.setdefault("DOCUMENT_STORAGE_DIR", tempfile.mkdtemp(prefix="edupath-test-storage-"))

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db import models  # noqa: F401


@pytest.fixture
async def sqlite_session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def app_client():
    """An `httpx.AsyncClient` wired to the real FastAPI app (ASGI transport,
    no live server) with the actual `app.db.session` engine — the one
    `get_session()` dependency injects on every request. SQLite `:memory:`
    engines use `StaticPool` (a single kept-alive connection), so this is
    the one fixture where schema + catalog seeding must go through that
    exact engine/session-factory rather than a fresh one, or requests would
    see an empty database. Drops and recreates all tables per test for
    isolation (the engine itself is a process-wide singleton, reused, not
    disposed, across tests).
    """
    from app.catalog.ingest import run_ingestion
    from app.db.session import SessionLocal, engine as app_engine
    from app.main import app

    async with app_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with SessionLocal() as session:
        await run_ingestion(session)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
def demo_mode(monkeypatch):
    """Turn DEMO_MODE on for one test (settings are a process-wide cached singleton)."""
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "demo_mode", True)
    return True


@pytest.fixture
async def other_client(app_client):
    """A second, independent learner session (its own cookie jar) against the same app + DB
    as `app_client` -- for learner-isolation tests. Both clients carry an explicit `session`
    cookie so their user ids differ (the dev fallback would make them the same user)."""
    from app.main import app

    app_client.cookies.set("session", "user-a")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test", cookies={"session": "user-b"}) as client:
        yield client


@pytest.fixture
async def catalog_session() -> AsyncSession:
    """A SQLite session with the real `data/dataset/*.json` domain pack
    (Phase 3) already ingested. Exercises the full ingestion pipeline
    (validate -> map -> embed -> write) against real curated data, not a
    hand-rolled fixture, so graph/catalog tests double as a regression check
    on the domain pack itself."""
    from app.catalog.ingest import run_ingestion

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        await run_ingestion(session)
    async with session_factory() as session:
        yield session
    await engine.dispose()
