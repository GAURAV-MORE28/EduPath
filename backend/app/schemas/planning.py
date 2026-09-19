"""Planner API request shapes (design §27: `POST /api/learners/me/plans`).
`WeeklyPlan`/`PlanItem` (the response shapes) live in `app/schemas/common.py`
-- the core §25.2 schema names -- per this project's existing convention
(`app/schemas/gap.py` does the same split for the Gap Engine)."""
from __future__ import annotations

from pydantic import BaseModel, Field


class CreatePlanRequest(BaseModel):
    """design §27's `{week_index?, dry_run?, hours?}`."""

    week_index: int = 0
    dry_run: bool = False
    hours: float | None = Field(default=None, gt=0, le=80)  # override the profile's weekly_hours for this run
