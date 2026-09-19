"""Data-access layer for the Planner's persisted tables (`WeeklyPlan`,
`PlanRevision`, `PlanItem` — design §28, `backend/app/db/models.py`)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import PlanItem, PlanRevision, WeeklyPlan


class PlanningRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -- WeeklyPlan -----------------------------------------------------------

    async def create_weekly_plan(self, plan: WeeklyPlan) -> WeeklyPlan:
        self.session.add(plan)
        await self.session.flush()
        return plan

    async def get_plan(self, plan_id: str) -> WeeklyPlan | None:
        result = await self.session.execute(select(WeeklyPlan).where(WeeklyPlan.plan_id == plan_id))
        return result.scalar_one_or_none()

    async def get_current_plan_for_learner(self, learner_id: str) -> WeeklyPlan | None:
        """Most recently created plan for this learner -- the rolling-horizon
        model (design §16.1) means each new `create_plan`/`patch_existing_plan`
        call is the new "current" one."""
        result = await self.session.execute(
            select(WeeklyPlan)
            .where(WeeklyPlan.learner_id == learner_id)
            .order_by(WeeklyPlan.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    # -- PlanRevision -----------------------------------------------------------

    async def create_revision(self, revision: PlanRevision) -> PlanRevision:
        self.session.add(revision)
        await self.session.flush()
        return revision

    async def list_revisions(self, plan_id: str) -> list[PlanRevision]:
        result = await self.session.execute(
            select(PlanRevision).where(PlanRevision.plan_id == plan_id).order_by(PlanRevision.revision_no)
        )
        return list(result.scalars().all())

    async def get_revision(self, revision_id: str) -> PlanRevision | None:
        result = await self.session.execute(select(PlanRevision).where(PlanRevision.revision_id == revision_id))
        return result.scalar_one_or_none()

    # -- PlanItem -----------------------------------------------------------

    async def create_items(self, items: list[PlanItem]) -> None:
        self.session.add_all(items)
        await self.session.flush()

    async def list_items_for_revision(self, revision_id: str) -> list[PlanItem]:
        result = await self.session.execute(
            select(PlanItem).where(PlanItem.revision_id == revision_id).order_by(PlanItem.day_slot)
        )
        return list(result.scalars().all())
