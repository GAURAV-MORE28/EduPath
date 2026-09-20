"""`POST /api/learners/me/chat`, `GET /api/learners/me/progress`,
`GET /api/decisions/{id}` (design §27) through the real FastAPI app (ASGI
transport, `app_client` -- see `tests/test_gap_api.py` for the same
pattern).
"""
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


async def test_chat_requires_intake_first(app_client):
    resp = await app_client.post("/api/learners/me/chat", json={"message": "what should I do this week"})
    assert resp.status_code == 404


async def test_chat_returns_a_grounded_conservative_answer(app_client):
    await app_client.post("/api/learners", json=INTAKE_BODY)
    resp = await app_client.post("/api/learners/me/chat", json={"message": "what are my skill gaps"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["degraded"] is True  # LLM_PROVIDER=none, this project's default
    assert body["conservative"] is True
    assert isinstance(body["citations"], list)
    assert body["answer"]


async def test_chat_out_of_scope_refuses_with_no_citations(app_client):
    await app_client.post("/api/learners", json=INTAKE_BODY)
    resp = await app_client.post("/api/learners/me/chat", json={"message": "what is the meaning of life"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["citations"] == []
    assert body["degraded"] is False


async def test_progress_requires_intake_first(app_client):
    resp = await app_client.get("/api/learners/me/progress")
    assert resp.status_code == 404


async def test_progress_reports_role_scoped_gaps_deterministically(app_client):
    await app_client.post("/api/learners", json=INTAKE_BODY)
    resp = await app_client.get("/api/learners/me/progress")
    assert resp.status_code == 200
    body = resp.json()
    assert body["role_id"] == "role.ml_engineer"
    assert body["period"] == "all_time"
    # "Python" was self-reported at intake -> E0 -> UNVERIFIED, never MET or acquired.
    assert "skill.python" not in {s["skill_id"] for s in body["acquired"]}
    assert len(body["remaining_gaps"]) > 0
    assert isinstance(body["narrative"], str)


async def test_progress_period_query_param_is_echoed(app_client):
    await app_client.post("/api/learners", json=INTAKE_BODY)
    resp = await app_client.get("/api/learners/me/progress", params={"period": "this_week"})
    assert resp.json()["period"] == "this_week"


async def test_get_unknown_decision_is_404(app_client):
    await app_client.post("/api/learners", json=INTAKE_BODY)
    resp = await app_client.get("/api/decisions/does-not-exist")
    assert resp.status_code == 404
