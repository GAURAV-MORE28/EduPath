"""DEMO_MODE (Phase 12, design §38): seeded learner, deterministic scenario, rehearsal
preflight, catalog bootstrap. The live system stays real -- these tests drive the same
services the API uses and assert on their real outputs."""
from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.db import models as m
from app.db.session import SessionLocal
from app.demo import service as demo_service
from app.demo.service import DEMO_LEARNER_ID, erase_learner_data

pytestmark = pytest.mark.asyncio


async def _count(model, **where) -> int:
    async with SessionLocal() as session:
        stmt = select(func.count()).select_from(model)
        for col, value in where.items():
            stmt = stmt.where(getattr(model, col) == value)
        return (await session.execute(stmt)).scalar_one()


async def test_demo_endpoints_are_disabled_unless_demo_mode(app_client):
    assert (await app_client.post("/api/demo/seed")).status_code == 403
    assert (await app_client.post("/api/demo/scripted-attempt")).status_code in {403, 404}  # 404: no learner yet
    # the read-only rehearsal checklist is always available
    assert (await app_client.get("/api/demo/preflight")).status_code == 200


async def test_seed_creates_the_persona_through_the_real_pipeline(app_client, demo_mode):
    resp = await app_client.post("/api/demo/seed")
    assert resp.status_code == 200
    seed = resp.json()
    assert seed["learner_id"] == DEMO_LEARNER_ID and seed["role_id"] == "role.ml_engineer"
    assert seed["claims_extracted"] > 0 and seed["claims_confirmed"] > 0 and seed["plan_item_count"] > 0
    assert "skill.python" in seed["seeded_skills"] and "skill.mlops_fundamentals" not in seed["seeded_skills"]
    assert seed["tutor_demo_questions"]

    async with SessionLocal() as session:
        evidence = (await session.execute(select(m.Evidence).where(m.Evidence.learner_id == DEMO_LEARNER_ID))).scalars().all()
        python_state = (
            await session.execute(select(m.LearnerSkillState).where(m.LearnerSkillState.skill_id == "skill.python"))
        ).scalar_one()
    sources = {e.source_type for e in evidence}
    assert {"document", "demo_seed"} <= sources  # the live resume's claims AND the labelled seeded evidence
    assert all(e.verified for e in evidence)
    assert (python_state.alpha, python_state.beta, python_state.tier_max) == (6.0, 2.0, "E2")


async def test_seed_is_idempotent_and_resets_the_persona(app_client, demo_mode):
    first = (await app_client.post("/api/demo/seed")).json()
    await app_client.post("/api/demo/scripted-attempt")  # dirty the state: signals, reflection, a revision
    assert await _count(m.PlanRevision) >= 2 and await _count(m.StruggleSignal) >= 1

    second = (await app_client.post("/api/demo/seed")).json()
    assert second["learner_id"] == first["learner_id"] == DEMO_LEARNER_ID
    assert await _count(m.LearnerProfile) == 1
    assert await _count(m.StruggleSignal) == 0 and await _count(m.ReflectionRecord) == 0
    assert await _count(m.PlanRevision) == 1  # only the fresh week-0 plan
    plan = (await app_client.get("/api/learners/me/plans/current")).json()
    assert plan["revision_no"] == 1


async def test_scripted_attempt_is_deterministic_across_reseeds(app_client, demo_mode):
    outcomes = []
    for _ in range(2):
        await app_client.post("/api/demo/seed")
        resp = await app_client.post("/api/demo/scripted-attempt")
        assert resp.status_code == 200
        body = resp.json()
        reflection = body["reflection"]
        outcomes.append(
            (
                body["score"],
                tuple(body["signal_classes"]),
                reflection["root_cause_skill_id"],
                reflection["misconception_id"],
                reflection["remediation_resource_ids"],
                tuple((op["op"], op["params"]["skill_id"]) for op in reflection["operators"]),
            )
        )
    assert outcomes[0] == outcomes[1]
    score, classes, root, misconception, _resources, operators = outcomes[0]
    assert score == 0.75 and root == "skill.chain_rule"  # score: the affected skill (backprop 3/4); chain_rule block 0/2 is the prerequisite signal
    assert root == "skill.chain_rule" and misconception == "misc.chain_rule_sum"
    assert "repeated_misconception" in classes and "missing_prerequisite" in classes
    assert ("INSERT_REMEDIATION", "skill.chain_rule") in operators and ("ADD_PROBE", "skill.chain_rule") in operators


async def test_scripted_attempt_never_reveals_answer_keys(app_client, demo_mode):
    await app_client.post("/api/demo/seed")
    text = (await app_client.post("/api/demo/scripted-attempt")).text
    assert "is_key" not in text and "chosen_option" not in text


async def test_scripted_answers_resolve_to_real_distractors_in_the_bank(catalog_session):
    """The scenario must never drift from the item bank again (it did before Phase 12: it
    scripted a misc.chain_rule_sum distractor on items that only carry it on the *key*)."""
    scenario = demo_service.load_scenario()
    ids = [a["item_id"] for a in scenario["scripted_attempt"]["answers"]]
    from app.repositories.catalog_repository import CatalogRepository

    items = {i.item_id: i for i in await CatalogRepository(catalog_session).get_practice_items_by_ids(ids)}
    assert set(items) == set(ids)
    for answer in scenario["scripted_attempt"]["answers"]:
        item = items[answer["item_id"]]
        idx = demo_service._option_index(item, chosen_is_key=answer["chosen_is_key"], misconception_id=answer["chosen_misconception_id"])
        option = item.options[idx]
        assert bool(option["is_key"]) is bool(answer["chosen_is_key"])
        if not answer["chosen_is_key"]:
            assert option["misconception_id"] == answer["chosen_misconception_id"], f"{item.item_id}: no such wrong option"


async def test_erase_learner_data_removes_every_owned_row(app_client, demo_mode):
    await app_client.post("/api/demo/seed")
    await app_client.post("/api/demo/scripted-attempt")
    await app_client.post("/api/learners/me/chat", json={"message": "Why did my plan change?"})
    from sqlalchemy import text

    async with SessionLocal() as session:
        # SQLite does not enforce foreign keys by default; Postgres does. Turn enforcement on so a wrong
        # delete order fails here, not in production (the plan tables also reference each other in a cycle).
        await session.execute(text("PRAGMA foreign_keys=ON"))
        try:
            await erase_learner_data(session, DEMO_LEARNER_ID)
            await session.commit()
        finally:
            await session.execute(text("PRAGMA foreign_keys=OFF"))
            await session.commit()
    for model in (
        m.LearnerProfile, m.Document, m.Evidence, m.LearnerSkillState, m.PendingClaim, m.WeeklyPlan, m.PlanRevision, m.PlanItem,
        m.PracticeSession, m.Assessment, m.StruggleSignal, m.LearnerMisconception, m.ReflectionRecord, m.DecisionRecord,
    ):
        assert await _count(model) == 0, model.__tablename__
    assert await _count(m.AgentRun, learner_id=DEMO_LEARNER_ID) == 0
    assert await _count(m.Skill) > 0  # the shared catalog is untouched


async def test_preflight_reports_ready_on_a_seeded_catalog(app_client, demo_mode):
    body = (await app_client.get("/api/demo/preflight")).json()
    assert body["ready"] is True and body["demo_mode"] is True
    checks = {c["name"]: c for c in body["checks"]}
    assert {"graph_loaded", "catalog_links", "item_bank", "demo_scenario", "llm_mode", "demo_mode"} <= set(checks)
    assert all(c["ok"] for c in checks.values())
    assert "reduced-intelligence" in checks["llm_mode"]["detail"]  # LLM_PROVIDER=none is stated, not hidden


async def test_preflight_fails_loudly_when_the_scenario_drifts_from_the_bank(app_client, monkeypatch):
    real = demo_service.load_scenario()
    real["scripted_attempt"]["answers"][0]["item_id"] = "item.does_not_exist.1"
    monkeypatch.setattr(demo_service, "load_scenario", lambda: real)
    body = (await app_client.get("/api/demo/preflight")).json()
    assert body["ready"] is False
    failing = [c for c in body["checks"] if not c["ok"]]
    assert failing[0]["name"] == "demo_scenario" and "item.does_not_exist.1" in failing[0]["detail"]


async def test_preflight_flags_broken_catalog_links(app_client):
    async with SessionLocal() as session:
        resource = (await session.execute(select(m.Resource).limit(1))).scalar_one()
        resource.link_status = "broken"
        await session.commit()
    body = (await app_client.get("/api/demo/preflight")).json()
    assert body["ready"] is False
    assert next(c for c in body["checks"] if c["name"] == "catalog_links")["ok"] is False


async def test_ensure_catalog_seeds_an_empty_database_once(sqlite_session):
    from app.catalog.bootstrap import ensure_catalog

    first = await ensure_catalog(sqlite_session)
    assert first is not None and first.skill_count > 100
    assert await ensure_catalog(sqlite_session) is None  # populated: never re-ingested over learner FKs
