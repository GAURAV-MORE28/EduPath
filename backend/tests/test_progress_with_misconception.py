"""Regression: `GET /api/learners/me/progress` must work for a learner who has
an open misconception. `LearnerMisconception` has no `skill_id`, and the report
builder used to read one, so the endpoint returned 500 as soon as a failed
assessment had produced a misconception (found while wiring the Phase 11 UI)."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio

INTAKE_BODY = {
    "current_skills": ["Python"],
    "experience_summary": "Third-year student.",
    "target_role_id": "role.ml_engineer",
    "career_goal": "Become an ML engineer",
    "weekly_hours": 8,
}


async def _tagged_wrong_option(item_id: str) -> int:
    from app.db.session import SessionLocal
    from app.repositories.catalog_repository import CatalogRepository

    async with SessionLocal() as session:
        item = await CatalogRepository(session).get_practice_item(item_id)
    for i, opt in enumerate(item.options):
        if not opt.get("is_key") and opt.get("misconception_id"):
            return i
    return next(i for i, opt in enumerate(item.options) if not opt.get("is_key"))


async def test_progress_reports_after_a_misconception_is_detected(app_client):
    await app_client.post("/api/learners", json=INTAKE_BODY)
    await app_client.post("/api/learners/me/plans", json={})
    practice = (
        await app_client.post("/api/learners/me/practice", json={"skill_id": "skill.backpropagation", "purpose": "practice"})
    ).json()
    answers = [{"item_id": it["item_id"], "chosen_option": await _tagged_wrong_option(it["item_id"])} for it in practice["items"]]
    submitted = await app_client.post(f"/api/practice/{practice['set_id']}/submit", json={"answers": answers})
    assert submitted.status_code == 200

    resp = await app_client.get("/api/learners/me/progress")
    assert resp.status_code == 200
    assert resp.json()["role_id"] == "role.ml_engineer"
