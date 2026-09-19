"""End-to-end API tests for the Planner (design §27):
`POST /api/learners/me/plans`, `GET /api/learners/me/plans/current`, through
the real FastAPI app (ASGI transport -- `app_client` fixture,
`tests/conftest.py`). `LLM_PROVIDER=none` (this project's default), so the
Fallback Planner (`app/planning/fallback.py`) resolves every plan created
here end to end, exactly what a judge running this offline would see --
mirrors `tests/test_learners_api.py`'s framing.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio

INTAKE_BODY = {
    "current_skills": [],
    "experience_summary": "",
    "target_role_id": "role.ml_engineer",
    "career_goal": "Become an ML engineer",
    "weekly_hours": 6,
}


async def test_create_plan_requires_intake_first(app_client):
    resp = await app_client.post("/api/learners/me/plans", json={})
    assert resp.status_code == 404


async def test_create_plan_returns_a_valid_committed_plan(app_client):
    await app_client.post("/api/learners", json=INTAKE_BODY)
    resp = await app_client.post("/api/learners/me/plans", json={"week_index": 0})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "committed"
    assert body["degraded"] is True  # LLM_PROVIDER=none -> fallback planner resolved this plan
    assert body["week_index"] == 0

    total_minutes = sum(i["est_minutes"] for i in body["items"])
    assert total_minutes <= body["hours_budget"] * 60 * 0.9 + 1e-6  # V1 time budget, design §17.2

    for item in body["items"]:
        assert item["type"] in {"resource", "practice", "project", "probe", "review"}
        assert item["reason"]["text"]  # every item is explainable, design §16.6


async def test_get_current_plan_returns_the_created_plan(app_client):
    await app_client.post("/api/learners", json=INTAKE_BODY)
    create_resp = await app_client.post("/api/learners/me/plans", json={})
    plan_id = create_resp.json()["plan_id"]

    resp = await app_client.get("/api/learners/me/plans/current")
    assert resp.status_code == 200
    body = resp.json()
    assert body["plan_id"] == plan_id
    # GET orders items by day_slot (ties broken by insertion order, not
    # necessarily the create response's original ordering) -- compare as sets.
    assert {i["item_id"] for i in body["items"]} == {i["item_id"] for i in create_resp.json()["items"]}


async def test_get_current_plan_404_before_any_plan_exists(app_client):
    await app_client.post("/api/learners", json=INTAKE_BODY)
    resp = await app_client.get("/api/learners/me/plans/current")
    assert resp.status_code == 404


async def test_dry_run_does_not_persist_a_plan(app_client):
    await app_client.post("/api/learners", json=INTAKE_BODY)
    dry_resp = await app_client.post("/api/learners/me/plans", json={"dry_run": True})
    assert dry_resp.status_code == 200
    assert dry_resp.json()["status"] == "dry_run"

    resp = await app_client.get("/api/learners/me/plans/current")
    assert resp.status_code == 404  # dry run wrote nothing to weekly_plans


async def test_hours_override_is_respected(app_client):
    await app_client.post("/api/learners", json=INTAKE_BODY)
    resp = await app_client.post("/api/learners/me/plans", json={"hours": 1})
    assert resp.status_code == 200
    body = resp.json()
    assert body["hours_budget"] == 1
    total_minutes = sum(i["est_minutes"] for i in body["items"])
    assert total_minutes <= 1 * 60 * 0.9 + 1e-6
