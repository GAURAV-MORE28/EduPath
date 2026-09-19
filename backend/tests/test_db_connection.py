"""Database connection test: the session factory + ORM models work end to end
against SQLite (see conftest.py for why SQLite substitutes for Postgres here)."""
import pytest
from sqlalchemy import select

from app.db.models import User
from app.repositories.user_repository import UserRepository


@pytest.mark.asyncio
async def test_create_and_fetch_user(sqlite_session) -> None:
    repo = UserRepository(sqlite_session)
    created = await repo.create(User(user_id="u1", email_hash="hash123", consent_flags={}))
    assert created.user_id == "u1"

    fetched = await repo.get_by_id("u1")
    assert fetched is not None
    assert fetched.email_hash == "hash123"


@pytest.mark.asyncio
async def test_missing_user_returns_none(sqlite_session) -> None:
    result = await sqlite_session.execute(select(User).where(User.user_id == "nope"))
    assert result.scalar_one_or_none() is None
