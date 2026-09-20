"""End-to-end integration: the complete learner journey through the real HTTP API.

    Resume -> Profile -> Evidence -> Skill Graph -> Gap Analysis -> Objectives ->
    Retrieval -> Plan -> Practice -> Assessment -> Struggle -> Reflection ->
    Re-plan -> Report -> Tutor

Two variants of the same `JourneyDriver` (`app/demo/journey.py`): the *live* path
(intake -> resume upload -> claim confirmation, every step a real user action) and
the *seeded* path (`POST /api/demo/seed`). Both then run the identical downstream flow.
Everything is asserted against real responses -- no mocks, no scripted results.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db.models import AgentRun, AgentStep, DecisionRecord, PlanRevision, ReflectionRecord, StruggleSignal
from app.db.session import SessionLocal
from app.demo.journey import JourneyDriver

pytestmark = pytest.mark.asyncio


async def _assert_downstream_journey(report) -> None:
    assert report.ok, [s.error for s in report.steps if not s.ok]

    # -- Evidence / Skill Graph / Gap Analysis / Objectives --------------------------------
    evidence = report.payload("evidence")
    assert evidence, "the learner has evidence after profiling"
    assert all(e["tier"] in {"E0", "E1", "E2", "E3"} and e["verified"] for e in evidence)
    assert report.payload("skill_graph")["skill"]["skill_id"] == "skill.backpropagation"

    gaps = report.payload("gaps")
    assert gaps["objectives"], "gap analysis produced learning objectives"
    assert {g["status"] for g in gaps["gaps"]} <= {"MET", "WEAK", "UNVERIFIED", "MISSING", "BLOCKED"}
    layer = {g["skill_id"]: g["ordering_layer"] for g in gaps["gaps"] if g["ordering_layer"] >= 0}  # -1: not a gap (MET)
    for edge in gaps["prerequisite_edges"]:  # prerequisite consistency: never ordered after its dependent
        if edge["from_skill_id"] in layer and edge["to_skill_id"] in layer:
            assert layer[edge["from_skill_id"]] <= layer[edge["to_skill_id"]]

    # -- Retrieval -> Plan ---------------------------------------------------------------------
    plan = report.payload("plan")
    assert plan["items"], "the week has items"
    assert sum(i["est_minutes"] for i in plan["items"]) <= plan["hours_budget"] * 60 * 1.15
    assert all(i["resource_id"] or i["type"] in {"probe", "practice", "checkpoint"} for i in plan["items"])

    # -- Practice: answer keys and misconception tags never leave the server -------------------
    practice = report.payload("practice")
    assert practice["items"]
    for item in practice["items"]:
        assert set(item) == {"item_id", "skill_id", "difficulty", "stem", "options"}

    # -- Assessment -> Struggle -> Reflection -> Re-plan ---------------------------------------
    attempt = report.payload("scripted_attempt")
    assert {"repeated_misconception", "missing_prerequisite"} <= set(attempt["signal_classes"])
    reflection = attempt["reflection"]
    assert reflection["root_cause_skill_id"] == "skill.chain_rule"
    assert reflection["misconception_id"] == "misc.chain_rule_sum"
    assert reflection["needs_attention"] is False
    assert {"INSERT_REMEDIATION", "ADD_PROBE"} <= {op["op"] for op in reflection["operators"]}
    assert reflection["plan_revision_id"] and reflection["decision_id"]

    plan_after = report.payload("plan_after")
    assert plan_after["revision_no"] == plan["revision_no"] + 1
    after = {(i["type"], i["skill_id"]) for i in plan_after["items"]}
    assert ("review", "skill.chain_rule") in after and ("probe", "skill.chain_rule") in after
    assert len(report.payload("revisions")) >= 2

    # -- Report ------------------------------------------------------------------------------------
    progress = report.payload("progress")
    assert progress["role_id"] == "role.ml_engineer"
    # the failed prerequisite block dropped chain_rule out of "acquired"; the remediation is the next step
    assert "skill.chain_rule" not in {a["skill_id"] for a in progress["acquired"]}
    assert "skill.chain_rule" in {a["skill_id"] for a in progress["in_progress"] + progress["remaining_gaps"]}
    assert any(a["skill_id"] == "skill.chain_rule" for a in progress["next_steps"])
    assert any(a["status"] == "remediating" for a in progress["struggle_areas"])

    # -- Tutor ----------------------------------------------------------------------------------------
    for name in ("chat_1", "chat_2"):
        chat = report.payload(name)
        assert chat["answer"] and chat["citations"], name
    decision = report.payload("decision")
    assert decision["type"] == "reflection" and decision["output_ref"] == reflection["plan_revision_id"]
    assert decision["graph_paths"] and decision["graph_paths"][0][0] == "skill.chain_rule"

    # -- Adaptation events are durable records ---------------------------------------------------
    async with SessionLocal() as session:
        signals = (await session.execute(select(StruggleSignal))).scalars().all()
        assert {"repeated_misconception", "missing_prerequisite"} <= {s.signal_class for s in signals}
        assert (await session.execute(select(ReflectionRecord))).scalars().all()
        assert (await session.execute(select(DecisionRecord))).scalars().all()
        causes = {r.cause_type for r in (await session.execute(select(PlanRevision))).scalars().all()}
        assert "reflection" in causes


async def test_live_path_journey_resume_to_tutor(app_client, demo_mode):
    """The user-driven path: intake -> resume upload -> confirm claims -> ... -> tutor."""
    report = await JourneyDriver(app_client).run()
    assert report.payload("resume_upload")["claims_summary"]["extracted"] > 0
    assert report.payload("claims_confirm")["confirmed"] > 0
    await _assert_downstream_journey(report)


async def test_seeded_demo_journey_resume_to_tutor(app_client, demo_mode):
    """The rehearsal path: `POST /api/demo/seed` -> ... -> tutor (design §38)."""
    report = await JourneyDriver(app_client, demo_seed=True).run()
    seed = report.payload("demo_seed")
    assert seed["learner_id"] == "demo-learner-asha" and seed["claims_confirmed"] > 0 and seed["plan_item_count"] > 0
    await _assert_downstream_journey(report)


async def test_every_journey_action_left_a_persisted_run_with_steps(app_client, demo_mode):
    report = await JourneyDriver(app_client, demo_seed=True).run()
    assert report.ok
    async with SessionLocal() as session:
        runs = {r.run_id: r for r in (await session.execute(select(AgentRun))).scalars().all()}
        steps = (await session.execute(select(AgentStep))).scalars().all()
    for name in ("demo_seed", "plan", "practice", "scripted_attempt", "chat_1", "chat_2"):
        step = report.get(name)
        assert step.run_id in runs, f"{name} left no AgentRun"
        run = runs[step.run_id]
        assert run.learner_id == "demo-learner-asha" and run.user_id
        assert run.http_status == 200 and run.duration_ms > 0 and run.status in {"completed", "degraded"}
    assert steps and all(s.actor and s.kind and s.step_id and s.run_id in runs for s in steps)
