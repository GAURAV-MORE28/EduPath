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


@pytest.mark.asyncio
async def test_get_or_create_provisions_a_missing_user(sqlite_session) -> None:
    """Regression test: on real Postgres, `LearnerProfile.user_id` FK-references
    `users.user_id`, and the dev-mode session fallback (app/api/deps.py) has no
    real signup flow behind it -- without auto-provisioning here, intake fails
    a foreign-key constraint that SQLite (this test's dialect) doesn't enforce
    but Postgres does. See docs/ARCHITECTURE_CONTRACTS.md Contract Changes."""
    repo = UserRepository(sqlite_session)
    created = await repo.get_or_create("dev-user")
    assert created.user_id == "dev-user"
    assert created.email_hash  # synthesized, non-empty

    again = await repo.get_or_create("dev-user")
    assert again.user_id == created.user_id
    assert again.email_hash == created.email_hash  # same row, not recreated
