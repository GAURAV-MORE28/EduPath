"""`GET /api/learners/me/gaps` (design §27) through the real FastAPI app
(ASGI transport -- see `app_client` in `tests/conftest.py`), same pattern as
`tests/test_learners_api.py`. Exercises the wiring the pure
`tests/test_gap_engine.py` suite doesn't: role-from-profile default, the
`?role=` override, the "no profile yet" 404, and the actual HTTP response
shape a frontend gap-graph view would consume.
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


async def test_gaps_requires_intake_first(app_client):
    resp = await app_client.get("/api/learners/me/gaps")
    assert resp.status_code == 404


async def test_gaps_defaults_to_the_learner_target_role(app_client):
    await app_client.post("/api/learners", json=INTAKE_BODY)
    resp = await app_client.get("/api/learners/me/gaps")
    assert resp.status_code == 200
    body = resp.json()
    assert body["role_id"] == "role.ml_engineer"
    assert body["graph_version"]
    gap_ids = {g["skill_id"] for g in body["gaps"]}
    assert "skill.python" in gap_ids
    assert "skill.chain_rule" in gap_ids


async def test_gaps_covers_full_role_subgraph_with_valid_statuses(app_client):
    await app_client.post("/api/learners", json=INTAKE_BODY)
    body = (await app_client.get("/api/learners/me/gaps")).json()
    assert len(body["gaps"]) > 50  # role.ml_engineer's subgraph is well over 50 skills
    statuses = {g["status"] for g in body["gaps"]}
    assert statuses <= {"MET", "WEAK", "UNVERIFIED", "MISSING", "BLOCKED"}


async def test_gaps_reflects_self_reported_intake_skill_as_unverified(app_client):
    # Intake maps "Python" straight to E0 evidence (never MET on its own).
    await app_client.post("/api/learners", json=INTAKE_BODY)
    body = (await app_client.get("/api/learners/me/gaps")).json()
    python_gap = next(g for g in body["gaps"] if g["skill_id"] == "skill.python")
    assert python_gap["status"] == "UNVERIFIED"
    assert len(python_gap["evidence_ids"]) == 1


async def test_gaps_role_query_param_overrides_profile_target_role(app_client):
    await app_client.post("/api/learners", json=INTAKE_BODY)
    resp = await app_client.get("/api/learners/me/gaps", params={"role": "role.data_analyst"})
    assert resp.status_code == 200
    assert resp.json()["role_id"] == "role.data_analyst"


async def test_gaps_rejects_unsupported_role_override(app_client):
    await app_client.post("/api/learners", json=INTAKE_BODY)
    resp = await app_client.get("/api/learners/me/gaps", params={"role": "role.astronaut"})
    assert resp.status_code == 422
    assert "role not supported" in resp.json()["detail"]


async def test_gaps_response_includes_graph_visualization_fields(app_client):
    await app_client.post("/api/learners", json=INTAKE_BODY)
    body = (await app_client.get("/api/learners/me/gaps")).json()
    assert "prerequisite_edges" in body and body["prerequisite_edges"]
    edge = body["prerequisite_edges"][0]
    assert set(edge) == {"from_skill_id", "to_skill_id"}
    assert "layers" in body and isinstance(body["layers"], list)
    assert all(isinstance(layer, list) for layer in body["layers"])


async def test_gaps_confirmed_document_evidence_can_reach_weak(app_client):
    await app_client.post("/api/learners", json=INTAKE_BODY)
    resume = b"EXPERIENCE\nBuilt production Python services and pipelines for two years."
    await app_client.post("/api/learners/me/documents", files={"file": ("resume.txt", resume, "text/plain")})
    pending = (await app_client.get("/api/learners/me/claims/pending")).json()
    decisions = [{"claim_id": c["claim_id"], "action": "confirm"} for c in pending]
    await app_client.post("/api/learners/me/claims/confirm", json={"decisions": decisions})

    body = (await app_client.get("/api/learners/me/gaps")).json()
    python_gap = next(g for g in body["gaps"] if g["skill_id"] == "skill.python")
    # Intake's E0 self-report plus a confirmed document claim: tier_max
    # upgrades past E0, so this can no longer be stuck at UNVERIFIED.
    assert python_gap["status"] in {"WEAK", "MET"}
