"""Data-access layer for the Assessment/Mastery/Struggle-Detection tables
(`PracticeSession`, `Assessment`, `StruggleSignal`, `LearnerMisconception` —
design §28, `backend/app/db/models.py`)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Assessment, LearnerMisconception, PracticeSession, StruggleSignal


class AssessmentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -- PracticeSession ------------------------------------------------------

    async def create_practice_session(self, session_row: PracticeSession) -> PracticeSession:
        self.session.add(session_row)
        await self.session.flush()
        return session_row

    async def get_practice_session(self, learner_id: str, set_id: str) -> PracticeSession | None:
        result = await self.session.execute(
            select(PracticeSession).where(
                PracticeSession.set_id == set_id, PracticeSession.learner_id == learner_id
            )
        )
        return result.scalar_one_or_none()

    # -- Assessment -----------------------------------------------------------

    async def create_assessment(self, assessment: Assessment) -> Assessment:
        self.session.add(assessment)
        await self.session.flush()
        return assessment

    async def list_assessments_for_skill(self, learner_id: str, skill_id: str) -> list[Assessment]:
        result = await self.session.execute(
            select(Assessment)
            .where(Assessment.learner_id == learner_id, Assessment.skill_id == skill_id)
            .order_by(Assessment.submitted_at)
        )
        return list(result.scalars().all())

    # -- StruggleSignal ---------------------------------------------------------

    async def create_signal(self, signal: StruggleSignal) -> StruggleSignal:
        self.session.add(signal)
        await self.session.flush()
        return signal

    async def list_signals_for_learner(self, learner_id: str, *, status: str | None = None) -> list[StruggleSignal]:
        stmt = select(StruggleSignal).where(StruggleSignal.learner_id == learner_id)
        if status is not None:
            stmt = stmt.where(StruggleSignal.status == status)
        result = await self.session.execute(stmt.order_by(StruggleSignal.created_at))
        return list(result.scalars().all())

    async def count_prior_misconception_items(
        self, learner_id: str, misconception_id: str, *, since: datetime
    ) -> int:
        """Distinct prior *items* (design §19.2: "distinct items", not
        distinct attempts) whose chosen wrong answer was tagged
        `misconception_id`, across every `Assessment` this learner has
        submitted within the lookback window -- the source of truth for
        "suspected -> confirmed" across separate submissions (not just
        within one attempt), read directly from assessment history rather
        than re-deriving it from previously emitted signals.
        """
        result = await self.session.execute(
            select(Assessment).where(Assessment.learner_id == learner_id, Assessment.submitted_at >= since)
        )
        item_ids: set[str] = set()
        for assessment in result.scalars().all():
            for entry in assessment.items:
                if entry.get("misconception_id") == misconception_id:
                    item_ids.add(entry["item_id"])
        return len(item_ids)

    # -- LearnerMisconception -----------------------------------------------------

    async def get_learner_misconception(self, learner_id: str, misconception_id: str) -> LearnerMisconception | None:
        result = await self.session.execute(
            select(LearnerMisconception).where(
                LearnerMisconception.learner_id == learner_id,
                LearnerMisconception.misconception_id == misconception_id,
            )
        )
        return result.scalar_one_or_none()

    async def create_learner_misconception(self, row: LearnerMisconception) -> LearnerMisconception:
        self.session.add(row)
        await self.session.flush()
        return row

    async def list_open_misconceptions(self, learner_id: str, skill_id: str | None = None) -> list[LearnerMisconception]:
        stmt = select(LearnerMisconception).where(
            LearnerMisconception.learner_id == learner_id,
            LearnerMisconception.status.in_(("suspected", "confirmed", "remediating")),
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


def within_cooldown(last_remediated_at: datetime | None, *, cooldown_hours: int) -> bool:
    """design §19.4: "at most one reflection-triggered revision per
    (learner, skill) per 24h unless new assessed evidence exists." Applied
    here to remediation triggers specifically."""
    if last_remediated_at is None:
        return False
    now = datetime.now(timezone.utc)
    last = last_remediated_at if last_remediated_at.tzinfo else last_remediated_at.replace(tzinfo=timezone.utc)
    return now - last < timedelta(hours=cooldown_hours)
