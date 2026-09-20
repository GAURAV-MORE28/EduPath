"""Security (Phase 12, design §29, ARCHITECTURE_CONTRACTS.md §7/§13): learner isolation,
invalid tool calls, unsupported roles, broken resources.

Two independent sessions (`app_client` = user-a, `other_client` = user-b) share one app
and one database. Everything user-a creates must be invisible and immutable to user-b.
"""
from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.config import get_settings
from app.db import models as m
from app.db.session import SessionLocal

pytestmark = pytest.mark.asyncio

INTAKE = {"current_skills": ["Python"], "experience_summary": "", "target_role_id": "role.ml_engineer", "career_goal": "ML", "weekly_hours": 8}


async def _tagged_wrong_option(item_id: str) -> int:
    from app.repositories.catalog_repository import CatalogRepository

    async with SessionLocal() as session:
        item = await CatalogRepository(session).get_practice_item(item_id)
    for i, opt in enumerate(item.options):
        if not opt.get("is_key") and opt.get("misconception_id"):
            return i
    return next(i for i, opt in enumerate(item.options) if not opt.get("is_key"))


async def _victim_with_history(client) -> dict:
    """user-a: intake -> plan -> practice -> a struggling submission (=> reflection, revision, decision)."""
    assert (await client.post("/api/learners", json=INTAKE)).status_code == 201
    plan = (await client.post("/api/learners/me/plans", json={})).json()
    practice = (await client.post("/api/learners/me/practice", json={"skill_id": "skill.backpropagation", "purpose": "practice"})).json()
    answers = [{"item_id": i["item_id"], "chosen_option": await _tagged_wrong_option(i["item_id"])} for i in practice["items"]]
    submitted = await client.post(f"/api/practice/{practice['set_id']}/submit", json={"answers": answers})
    assert submitted.status_code == 200
    revisions = (await client.get("/api/learners/me/plans/current/revisions")).json()
    return {
        "plan_id": plan["plan_id"],
        "set_id": practice["set_id"],
        "item_id": plan["items"][0]["item_id"],
        "revision_ids": [r["revision_id"] for r in revisions],
        "current_revision_id": next(r["revision_id"] for r in revisions if r["is_current"]),
        "decision_id": (submitted.json().get("reflection") or {}).get("decision_id"),
        "learner_id": (await client.get("/api/learners/me/profile")).json()["learner_id"],
    }


async def _snapshot() -> dict:
    async with SessionLocal() as session:
        counts = {t.__tablename__: (await session.execute(select(func.count()).select_from(t))).scalar_one() for t in (m.PlanRevision, m.PlanItem, m.Assessment, m.Evidence, m.LearnerSkillState, m.StruggleSignal)}
        statuses = sorted((i.item_id, i.status) for i in (await session.execute(select(m.PlanItem))).scalars().all())
    return {"counts": counts, "statuses": statuses}


# -- learner isolation ---------------------------------------------------------------------------------


async def test_a_stranger_cannot_read_or_modify_another_learners_data(app_client, other_client):
    victim = await _victim_with_history(app_client)
    assert len(victim["revision_ids"]) >= 2 and victim["decision_id"]
    assert (await other_client.post("/api/learners", json=INTAKE)).status_code == 201  # user-b is a real learner too
    before = await _snapshot()

    plan_id, rev = victim["plan_id"], victim["current_revision_id"]
    probes = [
        ("GET", f"/api/learners/me/plans/{plan_id}/revisions/{rev}", None),
        ("POST", f"/api/learners/me/plans/{plan_id}/revisions/{rev}/revert", None),
        ("PATCH", f"/api/learners/me/plans/items/{victim['item_id']}", {"status": "done"}),
        ("POST", f"/api/practice/{victim['set_id']}/submit", {"answers": []}),
        ("GET", f"/api/decisions/{victim['decision_id']}", None),
    ]
    for method, path, body in probes:
        resp = await other_client.request(method, path, json=body)
        assert resp.status_code == 404, f"{method} {path} -> {resp.status_code} (a foreign id must look unknown)"
    assert await _snapshot() == before, "none of the probes changed anything"

    # user-b's own views contain none of user-a's data
    assert (await other_client.get("/api/learners/me/plans/current")).status_code == 404
    assert (await other_client.get("/api/learners/me/plans/current/revisions")).status_code == 404
    progress = (await other_client.get("/api/learners/me/progress")).json()
    assert victim["learner_id"] not in str(progress) and progress["struggle_areas"] == []
    evidence_b = (await other_client.get("/api/learners/me/evidence")).json()
    assert victim["learner_id"] not in str(evidence_b)
    # and user-a's data is intact
    assert (await app_client.get("/api/learners/me/plans/current")).json()["plan_id"] == plan_id


async def test_a_foreign_claim_id_is_ignored_when_confirming(app_client, other_client):
    await app_client.post("/api/learners", json=INTAKE)
    await app_client.post("/api/learners/me/documents", files={"file": ("r.md", b"Skills: Python, PyTorch, OpenCV", "text/markdown")})
    a_claims = (await app_client.get("/api/learners/me/claims/pending")).json()
    assert a_claims

    await other_client.post("/api/learners", json=INTAKE)
    resp = await other_client.post(
        "/api/learners/me/claims/confirm",
        json={"decisions": [{"claim_id": c["claim_id"], "action": "confirm"} for c in a_claims]},
    )
    assert resp.status_code == 200 and resp.json()["confirmed"] == 0 and resp.json()["evidence_created"] == []
    assert len((await app_client.get("/api/learners/me/claims/pending")).json()) == len(a_claims)  # untouched, still pending for user-a


async def test_the_body_can_never_choose_the_learner(app_client, other_client):
    victim = await _victim_with_history(app_client)
    resp = await other_client.post("/api/learners", json={**INTAKE, "learner_id": victim["learner_id"], "user_id": "user-a"})
    assert resp.status_code == 201
    assert resp.json()["learner_id"] != victim["learner_id"]  # server-generated, session-derived
    resp = await other_client.post("/api/learners/me/plans", json={"learner_id": victim["learner_id"]})
    assert resp.status_code == 200 and resp.json()["learner_id"] != victim["learner_id"]
    chat = await other_client.post("/api/learners/me/chat", json={"message": "what changed?", "learner_id": victim["learner_id"], "decision_id_hint": victim["decision_id"]})
    assert chat.status_code == 200 and victim["decision_id"] not in chat.text


async def test_chat_hints_naming_another_learners_decision_or_skill_reveal_nothing(app_client, other_client):
    victim = await _victim_with_history(app_client)
    await other_client.post("/api/learners", json=INTAKE)
    for hint in ({"decision_id_hint": victim["decision_id"]}, {"decision_id_hint": "not-a-real-decision"}, {"skill_id_hint": "skill.does_not_exist"}):
        resp = await other_client.post("/api/learners/me/chat", json={"message": "Why did my plan change?", **hint})
        assert resp.status_code == 200, hint
        assert victim["decision_id"] not in resp.text and victim["learner_id"] not in resp.text


async def test_learner_routes_require_a_session_outside_dev(app_client, monkeypatch):
    monkeypatch.setattr(get_settings(), "env", "prod")
    app_client.cookies.clear()
    for method, path in [("GET", "/api/learners/me/plans/current"), ("GET", "/api/learners/me/evidence"), ("POST", "/api/learners/me/chat"), ("GET", "/api/runs/anything-00000")]:
        resp = await app_client.request(method, path, json={"message": "x"} if method == "POST" else None)
        assert resp.status_code == 401, f"{method} {path}"


# -- invalid tool calls ------------------------------------------------------------------------------------------


async def _tutor_context(catalog_session):
    from app.graph.loader import GraphLoader
    from app.graph.queries import SkillGraphService
    from app.db.models import LearnerProfile, User
    from app.gateway.embedding_gateway import get_embedding_gateway
    from app.repositories.catalog_repository import CatalogRepository
    from app.tutor.service import build_tutor_context

    catalog_session.add(User(user_id="tool-user", email_hash="tool-user"))
    await catalog_session.flush()
    catalog_session.add(LearnerProfile(learner_id="tool-learner", user_id="tool-user", target_role_id="role.ml_engineer", career_goal="", experience_summary="", weekly_hours=6, preferences={}, constraints={}))
    await catalog_session.commit()
    graph = SkillGraphService(await GraphLoader(CatalogRepository(catalog_session)).load())
    return await build_tutor_context(catalog_session, graph, "tool-learner")


async def test_the_tutor_tool_inventory_is_read_only_and_closed(catalog_session):
    from app.tutor.tools import TOOL_REGISTRY

    assert len(TOOL_REGISTRY) == 9
    forbidden = ("commit", "write", "update", "delete", "set_", "create", "apply", "revert", "override")
    assert not [name for name in TOOL_REGISTRY if name.startswith(forbidden) or any(w in name for w in ("commit_", "_write", "_delete"))]


async def test_invalid_tool_calls_are_refused_or_degrade_to_an_empty_result(catalog_session):
    from app.tutor.tools import UnknownToolError, call_tool

    ctx = await _tutor_context(catalog_session)
    with pytest.raises(UnknownToolError):
        await call_tool(ctx, "commit_plan_revision", {"plan_id": "x"})  # side-effect tools do not exist for the Tutor
    with pytest.raises(UnknownToolError):
        await call_tool(ctx, "get_learner_state; DROP TABLE users", {})

    smuggled = await call_tool(ctx, "get_learner_state", {"learner_id": "someone-else"})  # a learner id can't be an argument
    assert smuggled.error and smuggled.data == {} and smuggled.citable_ids == set()

    for tool in ("explain_skill_path", "get_evidence", "search_resources"):  # hallucinated skill id: an error result, never a crash
        bogus = await call_tool(ctx, tool, {"skill_id": "skill.no_such_skill"})
        assert bogus.error and not bogus.citable_ids, tool  # and nothing citable is invented from it
    foreign = await call_tool(ctx, "get_decision", {"decision_id": "another-learners-decision"})
    assert not foreign.citable_ids and not foreign.data.get("decision")


# -- unsupported roles ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize("role", ["role.astronaut", "", "role.ml_engineer; DROP TABLE roles", "ROLE.ML_ENGINEER"])
async def test_an_unsupported_role_is_refused_never_invented(app_client, role):
    resp = await app_client.post("/api/learners", json={**INTAKE, "target_role_id": role})
    assert resp.status_code == 422
    assert "role not supported" in resp.text
    async with SessionLocal() as session:
        assert (await session.execute(select(func.count()).select_from(m.LearnerProfile))).scalar_one() == 0
        assert (await session.execute(select(func.count()).select_from(m.Role).where(m.Role.role_id == role))).scalar_one() == 0


async def test_unknown_roles_and_skills_on_read_paths_are_clean_errors(app_client):
    await app_client.post("/api/learners", json=INTAKE)
    resp = await app_client.get("/api/learners/me/gaps", params={"role": "role.astronaut"})
    assert resp.status_code in {404, 422} and resp.status_code < 500
    assert (await app_client.get("/api/learners/me/skills/skill.no_such_skill")).status_code == 404
    assert (await app_client.post("/api/learners/me/practice", json={"skill_id": "skill.no_such_skill"})).status_code == 422
    assert (await app_client.post("/api/learners/me/practice", json={"skill_id": "skill.python", "purpose": "hack"})).status_code < 500


# -- broken resources ------------------------------------------------------------------------------------------------


async def test_a_broken_resource_is_never_recommended_or_scheduled(app_client):
    async with SessionLocal() as session:
        targets = (await session.execute(select(m.ResourceSkill.resource_id).where(m.ResourceSkill.skill_id == "skill.cli_basics"))).scalars().all()
        assert targets
        for rid in targets:
            (await session.get(m.Resource, rid)).link_status = "broken"
        await session.commit()

    await app_client.post("/api/learners", json={**INTAKE, "current_skills": []})
    resp = await app_client.post("/api/learners/me/plans", json={})
    assert resp.status_code == 200
    plan = resp.json()
    scheduled = {i["resource_id"] for i in plan["items"] if i["resource_id"]}
    assert not scheduled & set(targets), "a resource whose link is broken must not be scheduled"
    # the plan is still a valid plan: everything scheduled is a real, healthy catalog resource
    async with SessionLocal() as session:
        for rid in scheduled:
            assert (await session.get(m.Resource, rid)).link_status == "ok"

    tutor = await app_client.post("/api/learners/me/chat", json={"message": "What resources should I use for the command line?", "skill_id_hint": "skill.cli_basics"})
    assert tutor.status_code == 200 and not set(targets) & set(tutor.json()["citations"])


async def test_retrieval_with_every_resource_for_a_skill_broken_returns_nothing_not_an_error(catalog_session):
    from app.gateway.embedding_gateway import get_embedding_gateway
    from app.graph.loader import GraphLoader
    from app.graph.queries import SkillGraphService
    from app.repositories.catalog_repository import CatalogRepository
    from app.retrieval.service import ResourceRetrievalService

    catalog = CatalogRepository(catalog_session)
    ids = (await catalog_session.execute(select(m.ResourceSkill.resource_id).where(m.ResourceSkill.skill_id == "skill.chain_rule"))).scalars().all()
    assert ids
    for rid in ids:
        (await catalog_session.get(m.Resource, rid)).link_status = "broken"
    await catalog_session.flush()
    graph = SkillGraphService(await GraphLoader(catalog).load())
    service = ResourceRetrievalService(graph=graph, catalog=catalog, embedding_gateway=get_embedding_gateway())
    recs = await service.recommend_for_skill(skill_id="skill.chain_rule", current_level=0)
    assert not {r.resource_id for r in recs} & set(ids)
