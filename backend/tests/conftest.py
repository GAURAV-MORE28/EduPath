"""Shared test fixtures.

Uses an in-memory SQLite engine for the smoke/DB tests so the suite runs
without a live Postgres instance. Real Postgres-only features (pgvector,
JSONB-specific queries) are exercised against Postgres once the phase that
needs them lands; Phase 1 only needs to prove connectivity + migrations.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

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
