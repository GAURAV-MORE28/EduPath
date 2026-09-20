"""Tutor tool inventory (`app/tutor/tools.py`) against the real curated
dataset (`catalog_session`) -- every tool never invents an ID: `citable_ids`
is always a subset of real, resolvable IDs the tool call itself just read.
"""
from __future__ import annotations

import pytest

from app.db.models import (
    DecisionRecord,
    Evidence,
    LearnerProfile,
    LearnerSkillState,
    PlanItem,
    PlanRevision,
    User,
    WeeklyPlan,
)
from app.graph.loader import GraphLoader
from app.graph.queries import SkillGraphService
from app.repositories.catalog_repository import CatalogRepository
from app.repositories.planning_repository import PlanningRepository
from app.repositories.reflection_repository import ReflectionRepository
from app.tutor import tools
from app.tutor.service import build_tutor_context

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def graph_service(catalog_session) -> SkillGraphService:
    skill_graph = await GraphLoader(CatalogRepository(catalog_session)).load()
    return SkillGraphService(skill_graph)


async def _make_learner(session, *, role_id: str = "role.ml_engineer") -> str:
    import uuid

    user = User(email_hash=f"hash-tutor-{uuid.uuid4()}")
    session.add(user)
    await session.flush()
    profile = LearnerProfile(user_id=user.user_id, target_role_id=role_id, weekly_hours=6.0, preferences={}, constraints={})
    session.add(profile)
    await session.flush()
    return profile.learner_id


async def _seed_met_evidence(session, learner_id: str, skill_id: str) -> str:
    evidence = Evidence(learner_id=learner_id, skill_id=skill_id, tier="E3", source_type="assessment", verified=True)
    session.add(evidence)
    session.add(LearnerSkillState(learner_id=learner_id, skill_id=skill_id, alpha=20.0, beta=1.0, band="proficient", confidence="high", n_obs=5, tier_max="E3"))
    await session.flush()
    return evidence.evidence_id


async def test_get_learner_state_citable_ids_are_real_skill_ids_and_role(catalog_session, graph_service):
    learner_id = await _make_learner(catalog_session)
    await _seed_met_evidence(catalog_session, learner_id, "skill.python")
    ctx = await build_tutor_context(catalog_session, graph_service, learner_id)

    result = await tools.get_learner_state(ctx)
    assert result.error is None
    assert "skill.python" in result.data["skills"]
    assert result.citable_ids >= {"skill.python", "role.ml_engineer"}


async def test_get_gaps_matches_gap_engine_and_cites_real_skills(catalog_session, graph_service):
    learner_id = await _make_learner(catalog_session)
    ctx = await build_tutor_context(catalog_session, graph_service, learner_id)

    result = await tools.get_gaps(ctx)
    assert result.data["role_id"] == "role.ml_engineer"
    # bounded for the model (Phase 12): the highest-priority open gaps, with the true total alongside
    open_gaps = [g for g in ctx.gap_result.gaps if g.status != "MET"]
    assert result.data["open_gaps_total"] == len(open_gaps)
    assert len(result.data["gaps"]) == min(len(open_gaps), tools.MAX_GAPS_SHOWN)
    priorities = [g["priority"] for g in result.data["gaps"]]
    assert priorities == sorted(priorities, reverse=True)
    gap_skill_ids = {g["skill_id"] for g in result.data["gaps"]}
    assert gap_skill_ids <= result.citable_ids
    # every cited skill must be a real graph node
    for skill_id in gap_skill_ids:
        ctx.graph.get_skill(skill_id)


async def test_get_current_plan_no_plan_yet(catalog_session, graph_service):
    learner_id = await _make_learner(catalog_session)
    ctx = await build_tutor_context(catalog_session, graph_service, learner_id)

    result = await tools.get_current_plan(ctx)
    assert result.data == {"plan": None}
    assert result.error == "no plan yet"
    assert result.citable_ids == set()


async def test_get_current_plan_and_get_revisions_with_a_real_plan(catalog_session, graph_service):
    learner_id = await _make_learner(catalog_session)
    planning_repo = PlanningRepository(catalog_session)
    plan = await planning_repo.create_weekly_plan(WeeklyPlan(learner_id=learner_id, week_index=0, hours_budget=6.0, status="committed"))
    revision = await planning_repo.create_revision(
        PlanRevision(plan_id=plan.plan_id, revision_no=1, parent_revision_id=None, cause_type="initial", cause_ref="", operators=[], diff={}, degraded=False, overall_reason="initial plan")
    )
    await planning_repo.create_items(
        [PlanItem(plan_id=plan.plan_id, revision_id=revision.revision_id, type="resource", objective_id="obj.1", skill_id="skill.python", resource_id=None, est_minutes=30, difficulty=1, day_slot=0, status="planned")]
    )
    plan.current_revision_id = revision.revision_id
    await catalog_session.flush()

    ctx = await build_tutor_context(catalog_session, graph_service, learner_id)

    plan_result = await tools.get_current_plan(ctx)
    assert plan_result.data["plan_id"] == plan.plan_id
    assert plan_result.citable_ids >= {plan.plan_id, revision.revision_id, "skill.python", "obj.1"}

    rev_result = await tools.get_revisions(ctx)
    assert [r["revision_id"] for r in rev_result.data["revisions"]] == [revision.revision_id]
    assert revision.revision_id in rev_result.citable_ids


async def test_get_evidence_returns_only_this_skills_evidence(catalog_session, graph_service):
    learner_id = await _make_learner(catalog_session)
    ev_id = await _seed_met_evidence(catalog_session, learner_id, "skill.python")

    ctx = await build_tutor_context(catalog_session, graph_service, learner_id)
    result = await tools.get_evidence(ctx, skill_id="skill.python")
    assert [e["evidence_id"] for e in result.data["evidence"]] == [ev_id]
    assert result.citable_ids == {"skill.python", ev_id}

    other = await tools.get_evidence(ctx, skill_id="skill.chain_rule")
    assert other.data["evidence"] == []


async def test_get_evidence_unknown_skill_id_is_a_tool_error_not_a_crash(catalog_session, graph_service):
    learner_id = await _make_learner(catalog_session)
    ctx = await build_tutor_context(catalog_session, graph_service, learner_id)
    result = await tools.get_evidence(ctx, skill_id="skill.does_not_exist")
    assert result.error == "unknown skill_id"


async def test_explain_skill_path_cites_every_skill_on_the_path(catalog_session, graph_service):
    learner_id = await _make_learner(catalog_session)
    ctx = await build_tutor_context(catalog_session, graph_service, learner_id)

    result = await tools.explain_skill_path(ctx, skill_id="skill.chain_rule")
    assert result.data["path"] is not None
    path_skill_ids = {step["skill_id"] for step in result.data["path"]}
    assert "skill.chain_rule" in path_skill_ids
    assert path_skill_ids <= result.citable_ids
    assert result.data["path_id"] in result.citable_ids


async def test_search_resources_never_invents_a_resource_id(catalog_session, graph_service):
    learner_id = await _make_learner(catalog_session)
    ctx = await build_tutor_context(catalog_session, graph_service, learner_id)

    result = await tools.search_resources(ctx, skill_id="skill.chain_rule")
    resource_ids = {r["resource_id"] for r in result.data["resources"]}
    assert resource_ids <= result.citable_ids
    real_targeting = set(ctx.graph.resources_targeting("skill.chain_rule"))
    assert resource_ids <= real_targeting


async def test_get_progress_buckets_and_citable_ids(catalog_session, graph_service):
    learner_id = await _make_learner(catalog_session)
    await _seed_met_evidence(catalog_session, learner_id, "skill.python")
    ctx = await build_tutor_context(catalog_session, graph_service, learner_id)

    result = await tools.get_progress(ctx)
    acquired_ids = {s["skill_id"] for s in result.data["acquired"]}
    assert "skill.python" in acquired_ids
    assert acquired_ids <= result.citable_ids


async def test_get_decision_unknown_id_returns_none_not_an_error_crash(catalog_session, graph_service):
    learner_id = await _make_learner(catalog_session)
    ctx = await build_tutor_context(catalog_session, graph_service, learner_id)

    result = await tools.get_decision(ctx, decision_id="does-not-exist")
    assert result.data == {"decision": None}
    assert result.error == "unknown decision_id"


async def test_get_decision_resolves_a_real_record_and_is_learner_scoped(catalog_session, graph_service):
    learner_id = await _make_learner(catalog_session)
    other_learner_id = await _make_learner(catalog_session)
    reflection_repo = ReflectionRepository(catalog_session)
    record = await reflection_repo.create_decision_record(
        DecisionRecord(
            learner_id=learner_id, type="reflection", inputs={"x": 1}, evidence_ids=["ev_1"],
            graph_paths=[["skill.chain_rule", "skill.backpropagation"]], rules_fired=["r1"], scores={},
            graph_version="v0.1.0-test", output_ref="rev_1",
        )
    )

    ctx = await build_tutor_context(catalog_session, graph_service, learner_id)
    result = await tools.get_decision(ctx, decision_id=record.decision_id)
    assert result.data["decision_id"] == record.decision_id
    assert result.citable_ids >= {record.decision_id, "ev_1", "skill.chain_rule", "skill.backpropagation", "rev_1"}

    other_ctx = await build_tutor_context(catalog_session, graph_service, other_learner_id)
    not_found = await tools.get_decision(other_ctx, decision_id=record.decision_id)
    assert not_found.error == "unknown decision_id"
