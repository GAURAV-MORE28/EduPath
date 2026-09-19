"""Data-access layer for the Learner Profiling + Evidence Pipeline tables
(`LearnerProfile`, `Document`, `Evidence`, `LearnerSkillState`,
`PendingClaim` — design §28, `backend/app/db/models.py`)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Document, Evidence, LearnerProfile, LearnerSkillState, PendingClaim


class ProfilingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -- LearnerProfile -----------------------------------------------------

    async def get_learner_profile_by_user_id(self, user_id: str) -> LearnerProfile | None:
        result = await self.session.execute(select(LearnerProfile).where(LearnerProfile.user_id == user_id))
        return result.scalar_one_or_none()

    async def get_learner_profile(self, learner_id: str) -> LearnerProfile | None:
        result = await self.session.execute(select(LearnerProfile).where(LearnerProfile.learner_id == learner_id))
        return result.scalar_one_or_none()

    async def create_learner_profile(self, profile: LearnerProfile) -> LearnerProfile:
        self.session.add(profile)
        await self.session.flush()
        return profile

    # -- Document -------------------------------------------------------------

    async def create_document(self, document: Document) -> Document:
        self.session.add(document)
        await self.session.flush()
        return document

    async def get_document(self, document_id: str) -> Document | None:
        result = await self.session.execute(select(Document).where(Document.document_id == document_id))
        return result.scalar_one_or_none()

    # -- PendingClaim -----------------------------------------------------------

    async def create_pending_claims(self, claims: list[PendingClaim]) -> None:
        self.session.add_all(claims)
        await self.session.flush()

    async def list_pending_claims(self, learner_id: str, status: str = "pending") -> list[PendingClaim]:
        result = await self.session.execute(
            select(PendingClaim)
            .where(PendingClaim.learner_id == learner_id, PendingClaim.status == status)
            .order_by(PendingClaim.created_at)
        )
        return list(result.scalars().all())

    async def get_pending_claim(self, learner_id: str, claim_id: str) -> PendingClaim | None:
        result = await self.session.execute(
            select(PendingClaim).where(PendingClaim.learner_id == learner_id, PendingClaim.claim_id == claim_id)
        )
        return result.scalar_one_or_none()

    # -- Evidence / LearnerSkillState --------------------------------------------

    async def create_evidence(self, evidence: Evidence) -> Evidence:
        self.session.add(evidence)
        await self.session.flush()
        return evidence

    async def list_evidence_for_learner(self, learner_id: str) -> list[Evidence]:
        result = await self.session.execute(select(Evidence).where(Evidence.learner_id == learner_id))
        return list(result.scalars().all())

    async def get_learner_skill_state(self, learner_id: str, skill_id: str) -> LearnerSkillState | None:
        result = await self.session.execute(
            select(LearnerSkillState).where(
                LearnerSkillState.learner_id == learner_id, LearnerSkillState.skill_id == skill_id
            )
        )
        return result.scalar_one_or_none()

    async def list_skill_states_for_learner(self, learner_id: str) -> list[LearnerSkillState]:
        result = await self.session.execute(
            select(LearnerSkillState).where(LearnerSkillState.learner_id == learner_id)
        )
        return list(result.scalars().all())
