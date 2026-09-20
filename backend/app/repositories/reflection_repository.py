"""Data-access layer for the Reflection tables (`ReflectionRecord`,
`DecisionRecord` -- design §28, `backend/app/db/models.py`)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DecisionRecord, ReflectionRecord, StruggleSignal


class ReflectionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -- ReflectionRecord -----------------------------------------------------

    async def create_reflection_record(self, record: ReflectionRecord) -> ReflectionRecord:
        self.session.add(record)
        await self.session.flush()
        return record

    async def last_reflection_at_for_skill(self, learner_id: str, skill_id: str) -> datetime | None:
        """The most recent `ReflectionRecord.created_at` for a struggle
        signal on `skill_id` -- design §19.4's cooldown, applied to any
        Reflection trigger (not just misconception remediation, which has
        its own tracker on `LearnerMisconception.last_remediated_at`)."""
        result = await self.session.execute(
            select(ReflectionRecord.created_at)
            .join(StruggleSignal, StruggleSignal.signal_id == ReflectionRecord.signal_id)
            .where(ReflectionRecord.learner_id == learner_id, StruggleSignal.skill_id == skill_id)
            .order_by(ReflectionRecord.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    # -- DecisionRecord -------------------------------------------------------

    async def create_decision_record(self, record: DecisionRecord) -> DecisionRecord:
        self.session.add(record)
        await self.session.flush()
        return record

    async def list_decision_records(self, learner_id: str, *, type_: str | None = None) -> list[DecisionRecord]:
        stmt = select(DecisionRecord).where(DecisionRecord.learner_id == learner_id)
        if type_ is not None:
            stmt = stmt.where(DecisionRecord.type == type_)
        result = await self.session.execute(stmt.order_by(DecisionRecord.created_at.desc()))
        return list(result.scalars().all())

    async def get_decision_record(self, learner_id: str, decision_id: str) -> DecisionRecord | None:
        """design §27's `GET /api/decisions/{id}` / the Tutor's `get_decision`
        tool (design §26.2) -- learner-scoped so a decision record can never
        be resolved across learners (ARCHITECTURE_CONTRACTS.md §9's row-level
        isolation)."""
        result = await self.session.execute(
            select(DecisionRecord).where(
                DecisionRecord.decision_id == decision_id, DecisionRecord.learner_id == learner_id
            )
        )
        return result.scalar_one_or_none()


def within_cooldown(last_at: datetime | None, *, cooldown_hours: int) -> bool:
    if last_at is None:
        return False
    now = datetime.now(timezone.utc)
    last = last_at if last_at.tzinfo else last_at.replace(tzinfo=timezone.utc)
    return now - last < timedelta(hours=cooldown_hours)
