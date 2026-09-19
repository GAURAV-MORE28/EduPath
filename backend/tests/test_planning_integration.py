"""End-to-end Planner tests against the real curated dataset
(`catalog_session` fixture, `tests/conftest.py`) -- Gap Engine (Phase 4) ->
candidate building (`app/planning/candidates.py`) -> the G2 Planning graph
(`app/orchestration/graphs.py`) -> deterministic validation
(`app/planning/validator.py`). `LLM_PROVIDER=none` (this project's default)
means the Fallback Planner resolves these plans, exercising the whole
"LLM unavailable -> deterministic path" flow with real graph/catalog data,
not just hand-built fixtures -- same "regression check on the domain pack
itself" role `tests/test_gap_engine.py`'s `graph_service` fixture plays.

Also covers `patch_existing_plan` (`app/planning/service.py`) end to end
through a real (SQLite) session -- the capability Reflection (Phase 8) will
later call.
"""
from __future__ import annotations

import pytest

from app.agents.planner import PlannerAgent
from app.db.models import LearnerProfile, User
from app.gap.engine import LearnerSkillRecord
from app.gateway.embedding_gateway import DegradedEmbeddingGateway
from app.gateway.llm_gateway import LLMGateway
from app.graph.loader import GraphLoader
from app.graph.queries import SkillGraphService
from app.orchestration.graphs import build_planning_graph
from app.orchestration.state import RunState
from app.planning.service import create_plan, patch_existing_plan
from app.planning.validator import effective_budget_minutes, validate_plan
from app.repositories.catalog_repository import CatalogRepository
from app.retrieval.service import ResourceRetrievalService


@pytest.fixture
async def graph_service(catalog_session) -> SkillGraphService:
    skill_graph = await GraphLoader(CatalogRepository(catalog_session)).load()
    return SkillGraphService(skill_graph)


def _e0(skill_id: str) -> LearnerSkillRecord:
    # E0 (self-reported only) -> UNVERIFIED under the Gap Engine's tier gate
    # (ARCHITECTURE_CONTRACTS.md §3), never MET -- exercises verify-before-teach probes.
    return LearnerSkillRecord(skill_id=skill_id, alpha=0.5, beta=1.0, tier_max="E0")


@pytest.mark.asyncio
async def test_full_pipeline_produces_a_valid_plan_from_the_real_catalog(catalog_session, graph_service):
    catalog = CatalogRepository(catalog_session)
    retrieval_service = ResourceRetrievalService(catalog, graph_service, DegradedEmbeddingGateway())
    planner_agent = PlannerAgent(LLMGateway())  # LLM_PROVIDER=none -> degrades -> fallback path exercised

    # skill.backpropagation's three hard prerequisites (chain_rule,
    # neural_network_fundamentals, activation_functions -- see
    # tests/test_gap_engine.py's tiny_graph_service docstring) all UNVERIFIED
    # too, so none of them is WEAK/MISSING and backpropagation itself is a
    # root gap (not BLOCKED) with a real "probe"-purpose bank item (design
    # §13.5's verify-before-teach).
    skill_records = [
        _e0("skill.chain_rule"),
        _e0("skill.neural_network_fundamentals"),
        _e0("skill.activation_functions"),
        _e0("skill.backpropagation"),
    ]

    graph = build_planning_graph(
        graph_service=graph_service, planner_agent=planner_agent, catalog=catalog, retrieval_service=retrieval_service
    )
    weekly_hours = 6.0
    initial_state: RunState = {
        "run_id": "run-test",
        "learner_id": "learner-test",
        "graph": "G2_planning",
        "status": "running",
        "counters": {},
        "data": {
            "role_id": "role.ml_engineer",
            "skill_records": skill_records,
            "evidence_records": [],
            "hours_budget_minutes": effective_budget_minutes(weekly_hours),
        },
    }

    final_state = await graph.ainvoke(initial_state)

    assert final_state["status"] == "completed"
    d = final_state["data"]
    assert d["final_degraded"] is True  # LLM unavailable -> Fallback Planner resolved this plan

    gap_result = d["gap_result"]
    assert any(g.skill_id == "skill.backpropagation" and g.status == "UNVERIFIED" for g in gap_result.gaps)

    items = d["final_items"]
    assert items  # backpropagation's real probe bank item makes this non-empty

    # Every referenced ID is real -- drawn from the catalog/graph, never invented
    # (ARCHITECTURE_CONTRACTS.md §7/§15).
    all_skill_ids = {s.skill_id for s in await catalog.get_all_skills()}
    all_resource_ids = {r.resource_id for r in await catalog.get_all_resources()}
    all_practice_item_ids = {i.item_id for i in await catalog.get_all_practice_items()}
    for item in items:
        assert item.skill_id in all_skill_ids
        if item.resource_id is not None:
            assert item.resource_id in all_resource_ids
        for pid in item.practice_item_ids:
            assert pid in all_practice_item_ids

    gaps_by_skill = {g.skill_id: g for g in gap_result.gaps}
    hard_prereqs_by_skill = {s: graph_service.direct_prerequisites(s, include_soft=False) for s in gaps_by_skill}
    result = validate_plan(
        items,
        candidate_sets=d["candidate_sets"],
        gaps_by_skill=gaps_by_skill,
        hard_prereqs_by_skill=hard_prereqs_by_skill,
        hours_budget_minutes=d["hours_budget_minutes"],
    )
    assert result.passed


@pytest.mark.asyncio
async def test_create_plan_then_patch_existing_plan_end_to_end(catalog_session, graph_service):
    """`app/planning/service.py`'s two entry points, against a real (SQLite)
    session: `create_plan` persists a `WeeklyPlan`/`PlanRevision`/`PlanItem`
    set, then `patch_existing_plan` reads that plan back and produces a
    second, higher `revision_no` for the *same* `plan_id` -- the capability
    Reflection (Phase 8) will later call, per the Phase 5 brief."""
    session = catalog_session
    catalog = CatalogRepository(session)
    embedding_gateway = DegradedEmbeddingGateway()
    llm_gateway = LLMGateway()

    user = User(email_hash="test-hash")
    session.add(user)
    await session.flush()
    profile = LearnerProfile(
        user_id=user.user_id, target_role_id="role.ml_engineer", weekly_hours=6.0, preferences={}, constraints={}
    )
    session.add(profile)
    await session.flush()

    plan = await create_plan(
        session=session,
        graph_service=graph_service,
        llm_gateway=llm_gateway,
        embedding_gateway=embedding_gateway,
        learner_id=profile.learner_id,
        role_id="role.ml_engineer",
        week_index=0,
        weekly_hours=6.0,
    )
    await session.commit()

    assert plan.revision_no == 1
    assert plan.degraded is True

    patched = await patch_existing_plan(
        session=session,
        graph_service=graph_service,
        llm_gateway=llm_gateway,
        embedding_gateway=embedding_gateway,
        learner_id=profile.learner_id,
        role_id="role.ml_engineer",
        plan_id=plan.plan_id,
        operators=[{"op": "swap_resource", "reason": "learner requested a change"}],
    )
    await session.commit()

    assert patched.plan_id == plan.plan_id  # same plan, new revision
    assert patched.revision_no == 2
