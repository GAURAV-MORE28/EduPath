"""End-to-end API tests for Practice & Assessment (design §27):
`POST /api/learners/me/practice`, `POST /api/practice/{set_id}/submit`,
through the real FastAPI app (`app_client` fixture, `tests/conftest.py`).
Mirrors `tests/test_learners_api.py`/`tests/test_plans_api.py`'s framing.
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


async def test_create_practice_set_requires_intake_first(app_client):
    resp = await app_client.post("/api/learners/me/practice", json={"skill_id": "skill.chain_rule"})
    assert resp.status_code == 404


async def test_create_practice_set_returns_items_without_keys_or_misconception_tags(app_client):
    await app_client.post("/api/learners", json=INTAKE_BODY)
    resp = await app_client.post("/api/learners/me/practice", json={"skill_id": "skill.chain_rule"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["skill_id"] == "skill.chain_rule"
    assert body["items"]
    for item in body["items"]:
        assert set(item.keys()) == {"item_id", "skill_id", "difficulty", "stem", "options"}
        assert all(isinstance(o, str) for o in item["options"])  # option text only -- no is_key/misconception_id


async def test_create_practice_set_unknown_skill_is_rejected(app_client):
    await app_client.post("/api/learners", json=INTAKE_BODY)
    resp = await app_client.post("/api/learners/me/practice", json={"skill_id": "skill.does_not_exist"})
    assert resp.status_code == 422


async def test_submit_unknown_set_id_is_404(app_client):
    await app_client.post("/api/learners", json=INTAKE_BODY)
    resp = await app_client.post("/api/practice/not-a-real-set-id/submit", json={"answers": []})
    assert resp.status_code == 404


async def test_full_practice_round_trip_with_correct_answers(app_client):
    await app_client.post("/api/learners", json=INTAKE_BODY)
    create_resp = await app_client.post("/api/learners/me/practice", json={"skill_id": "skill.python"})
    assert create_resp.status_code == 200
    practice_set = create_resp.json()
    assert practice_set["items"]

    # We don't know the key server-side without cheating -- submit index 0 for
    # every item and just assert the response shape/consistency, not a particular score.
    answers = [{"item_id": it["item_id"], "chosen_option": 0} for it in practice_set["items"]]
    submit_resp = await app_client.post(f"/api/practice/{practice_set['set_id']}/submit", json={"answers": answers})
    assert submit_resp.status_code == 200
    body = submit_resp.json()

    assert body["result"]["skill_id"] == "skill.python"
    assert body["result"]["purpose"] == "practice"
    assert len(body["result"]["items"]) == len(answers)
    assert 0.0 <= body["result"]["score"] <= 1.0
    for item in body["result"]["items"]:
        # design §18.3: the submit response is server-authoritative -- it may reveal
        # correctness/misconception_id (that's the point of a graded result), but the
        # request never told the server which one was right.
        assert "correct" in item


async def test_a_second_set_before_any_submission_repeats_the_same_items(app_client):
    """design §18.2 point 2's "excluding previously seen items" is keyed off
    *submitted* assessments (`app/assessment/service.py`'s `seen_item_ids`),
    not merely-assembled-but-unanswered sets -- so two sets created back to
    back with nothing submitted in between are identical. This documents
    that behavior explicitly rather than leaving it implicit."""
    await app_client.post("/api/learners", json=INTAKE_BODY)
    first = (await app_client.post("/api/learners/me/practice", json={"skill_id": "skill.python"})).json()
    second = (await app_client.post("/api/learners/me/practice", json={"skill_id": "skill.python"})).json()
    first_ids = {i["item_id"] for i in first["items"]}
    second_ids = {i["item_id"] for i in second["items"]}
    assert first_ids and first_ids == second_ids


async def test_a_second_set_after_submission_excludes_previously_seen_items(app_client):
    await app_client.post("/api/learners", json=INTAKE_BODY)
    first = (await app_client.post("/api/learners/me/practice", json={"skill_id": "skill.python"})).json()
    answers = [{"item_id": it["item_id"], "chosen_option": 0} for it in first["items"]]
    await app_client.post(f"/api/practice/{first['set_id']}/submit", json={"answers": answers})

    second = (await app_client.post("/api/learners/me/practice", json={"skill_id": "skill.python"})).json()
    first_ids = {i["item_id"] for i in first["items"]}
    second_ids = {i["item_id"] for i in second["items"]}
    assert first_ids.isdisjoint(second_ids) or not second_ids  # excluded, or the bank was exhausted
