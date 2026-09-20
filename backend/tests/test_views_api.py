"""Read-model endpoints the frontend depends on (Phase 11), plus the trace
bus's replay buffer and `X-Run-Id` wiring. Same ASGI-transport pattern as
`tests/test_gap_api.py`."""
from __future__ import annotations

import pytest

from app.schemas.envelope import TraceEvent
from app.sse.trace import TraceBus, current_run_id, emit, trace_bus

pytestmark = pytest.mark.asyncio

INTAKE_BODY = {
    "current_skills": ["Python"],
    "experience_summary": "Third-year student.",
    "target_role_id": "role.ml_engineer",
    "career_goal": "Become an ML engineer",
    "weekly_hours": 8,
}


async def test_roles_come_from_the_catalog(app_client):
    resp = await app_client.get("/api/roles")
    assert resp.status_code == 200
    roles = resp.json()
    assert {r["role_id"] for r in roles} >= {"role.ml_engineer", "role.data_analyst"}
    assert all(r["title"] and r["required_skill_count"] > 0 for r in roles)


async def test_catalog_skills_filter_by_ids(app_client):
    resp = await app_client.get("/api/catalog/skills", params={"ids": "skill.python,skill.chain_rule"})
    assert resp.status_code == 200
    assert {s["skill_id"] for s in resp.json()} == {"skill.python", "skill.chain_rule"}


async def test_catalog_resources_require_ids_and_return_metadata(app_client):
    assert (await app_client.get("/api/catalog/resources")).status_code == 422
    all_resources = await app_client.get("/api/catalog/skills")
    assert all_resources.status_code == 200


async def test_profile_requires_intake_then_round_trips(app_client):
    assert (await app_client.get("/api/learners/me/profile")).status_code == 404
    await app_client.post("/api/learners", json=INTAKE_BODY)
    resp = await app_client.get("/api/learners/me/profile")
    assert resp.status_code == 200
    body = resp.json()
    assert body["target_role_id"] == "role.ml_engineer"
    assert body["weekly_hours"] == 8


async def test_evidence_lists_intake_claims_with_their_tier(app_client):
    await app_client.post("/api/learners", json=INTAKE_BODY)
    resp = await app_client.get("/api/learners/me/evidence")
    assert resp.status_code == 200
    ev = resp.json()
    python = next(e for e in ev if e["skill_id"] == "skill.python")
    assert python["tier"] == "E0"
    assert python["source_type"] == "intake"
    assert python["skill_label"]


async def test_skill_detail_bundles_gap_evidence_and_prerequisites(app_client):
    await app_client.post("/api/learners", json=INTAKE_BODY)
    resp = await app_client.get("/api/learners/me/skills/skill.backpropagation")
    assert resp.status_code == 200
    body = resp.json()
    assert body["skill"]["skill_id"] == "skill.backpropagation"
    assert body["gap"]["required_level"] >= 1
    assert body["prerequisites"], "backpropagation has hard prerequisites in the curated graph"
    assert any(p["skill_id"] == "skill.chain_rule" for p in body["prerequisites"])
    assert (await app_client.get("/api/learners/me/skills/skill.nope")).status_code == 404


async def test_plan_revisions_and_item_status(app_client):
    await app_client.post("/api/learners", json=INTAKE_BODY)
    assert (await app_client.get("/api/learners/me/plans/current/revisions")).status_code == 404

    plan = (await app_client.post("/api/learners/me/plans", json={})).json()
    revisions = (await app_client.get("/api/learners/me/plans/current/revisions")).json()
    assert [r["revision_no"] for r in revisions] == [1]
    assert revisions[0]["is_current"] is True

    detail = await app_client.get(f"/api/learners/me/plans/{plan['plan_id']}/revisions/{revisions[0]['revision_id']}")
    assert detail.status_code == 200
    assert len(detail.json()["items"]) == len(plan["items"])

    if plan["items"]:
        item_id = plan["items"][0]["item_id"]
        patched = await app_client.patch(f"/api/learners/me/plans/items/{item_id}", json={"status": "done"})
        assert patched.status_code == 200 and patched.json()["status"] == "done"
        current = (await app_client.get("/api/learners/me/plans/current")).json()
        assert next(i for i in current["items"] if i["item_id"] == item_id)["status"] == "done"
        assert (await app_client.patch(f"/api/learners/me/plans/items/{item_id}", json={"status": "bogus"})).status_code == 422
    assert (await app_client.patch("/api/learners/me/plans/items/nope", json={"status": "done"})).status_code == 404


async def test_trace_bus_replays_history_to_late_subscribers():
    bus = TraceBus()
    await bus.publish(TraceEvent(run_id="run-a", step_id="s1", agent_or_service="Planner", kind="output", summary="one"))
    queue = bus.subscribe("run-a")
    assert queue.get_nowait().summary == "one"
    assert bus.subscribe("run-b").empty()


async def test_emit_is_a_noop_without_a_run_id_and_publishes_with_one():
    await emit("Planner", "output", "ignored")  # no run id set: nothing happens, nothing raises
    token = current_run_id.set("run-emit-test-1")
    try:
        await emit("Gap Engine", "decision", "built objectives")
    finally:
        current_run_id.reset(token)
    queue = trace_bus.subscribe("run-emit-test-1")
    event = queue.get_nowait()
    assert (event.agent_or_service, event.summary) == ("Gap Engine", "built objectives")
    trace_bus.unsubscribe("run-emit-test-1", queue)


async def test_x_run_id_header_produces_real_plan_trace_events(app_client):
    await app_client.post("/api/learners", json=INTAKE_BODY)
    run_id = "trace-run-plan-0001"
    resp = await app_client.post("/api/learners/me/plans", json={}, headers={"X-Run-Id": run_id})
    assert resp.status_code == 200
    queue = trace_bus.subscribe(run_id)
    actors = []
    while not queue.empty():
        actors.append(queue.get_nowait().agent_or_service)
    trace_bus.unsubscribe(run_id, queue)
    assert actors[:3] == ["Gap Engine", "Planner", "Plan Validator"]
