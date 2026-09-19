"""User repository — the one concrete repository Phase 1 needs to prove the
data-access layer pattern against a real table."""
from __future__ import annotations

import hashlib

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, user_id: str) -> User | None:
        result = await self.session.execute(select(User).where(User.user_id == user_id))
        return result.scalar_one_or_none()

    async def create(self, user: User) -> User:
        self.session.add(user)
        await self.session.commit()
        await self.session.refresh(user)
        return user

    async def get_or_create(self, user_id: str) -> User:
        """Auto-provisions a minimal `User` row for `user_id` if one doesn't
        exist yet. A stand-in for a real signup flow, which doesn't exist
        yet (`app/api/deps.py`'s session boundary is a placeholder — see
        IMPLEMENTATION_STATE.md "Known Issues"): any learner-scoped write
        that FK-references `users.user_id` (e.g. `LearnerProfile`) needs a
        real row there, and Postgres enforces that FK even though the
        SQLite test dialect does not (a real bug this caught — see Contract
        Changes). `email_hash` is synthesized from `user_id` since there is
        no real email to hash yet; a real auth flow replaces this method's
        callers with actual signup-created rows.
        """
        existing = await self.get_by_id(user_id)
        if existing is not None:
            return existing
        user = User(user_id=user_id, email_hash=hashlib.sha256(user_id.encode("utf-8")).hexdigest())
        self.session.add(user)
        await self.session.flush()
        return user
