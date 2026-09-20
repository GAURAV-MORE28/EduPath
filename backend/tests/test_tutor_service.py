"""G4 Tutor end-to-end (`app/tutor/service.py::run_chat`, the compiled
`build_tutor_graph`) against the real curated dataset. `LLM_PROVIDER=none`
is this project's permanent default (see every other agent's test file for
the same note), so these exercise the *real, always-live* path: the
deterministic conservative answer, never a mocked LLM response — matching
`tests/test_planning_integration.py`'s "the fallback path is what's actually
exercised" precedent.
"""
from __future__ import annotations

import uuid

import pytest

from app.db.models import LearnerProfile, PlanItem, PlanRevision, User, WeeklyPlan
from app.gateway.llm_gateway import LLMGateway
from app.graph.loader import GraphLoader
from app.graph.queries import SkillGraphService
from app.repositories.catalog_repository import CatalogRepository
from app.repositories.planning_repository import PlanningRepository
from app.tutor.service import run_chat

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def graph_service(catalog_session) -> SkillGraphService:
    skill_graph = await GraphLoader(CatalogRepository(catalog_session)).load()
    return SkillGraphService(skill_graph)


async def _make_learner(session) -> str:
    user = User(email_hash=f"hash-tutor-svc-{uuid.uuid4()}")
    session.add(user)
    await session.flush()
    profile = LearnerProfile(user_id=user.user_id, target_role_id="role.ml_engineer", weekly_hours=6.0, preferences={}, constraints={})
    session.add(profile)
    await session.flush()
    return profile.learner_id


async def test_out_of_scope_question_gets_a_refusal_with_no_citations(catalog_session, graph_service):
    learner_id = await _make_learner(catalog_session)
    answer = await run_chat(
        session=catalog_session, graph=graph_service, llm_gateway=LLMGateway(), learner_id=learner_id,
        message="what is the meaning of life",
    )
    assert answer.citations == []
    assert not answer.degraded
    assert not answer.conservative
    assert "learning journey" in answer.answer or "rephrase" in answer.answer


async def test_gap_question_falls_back_to_a_grounded_conservative_answer(catalog_session, graph_service):
    """LLM_PROVIDER=none (this project's default) means `compose_answer`
    always degrades -- the conservative answer is what actually runs, and it
    must cite only real IDs `call_tools` returned this turn."""
    learner_id = await _make_learner(catalog_session)
    answer = await run_chat(
        session=catalog_session, graph=graph_service, llm_gateway=LLMGateway(), learner_id=learner_id,
        message="what are my skill gaps",
    )
    assert answer.degraded
    assert answer.conservative
    assert answer.citations  # grounded in at least one real ID
    for cid in answer.citations:
        # every citation must resolve to a real skill in the curated graph
        graph_service.get_skill(cid)


async def test_plan_question_with_a_real_plan_cites_real_plan_ids(catalog_session, graph_service):
    learner_id = await _make_learner(catalog_session)
    planning_repo = PlanningRepository(catalog_session)
    plan = await planning_repo.create_weekly_plan(WeeklyPlan(learner_id=learner_id, week_index=0, hours_budget=6.0, status="committed"))
    revision = await planning_repo.create_revision(
        PlanRevision(plan_id=plan.plan_id, revision_no=1, parent_revision_id=None, cause_type="initial", cause_ref="", operators=[], diff={}, degraded=False, overall_reason="")
    )
    await planning_repo.create_items(
        [PlanItem(plan_id=plan.plan_id, revision_id=revision.revision_id, type="resource", objective_id="obj.1", skill_id="skill.python", resource_id=None, est_minutes=30, difficulty=1, day_slot=0, status="planned")]
    )
    plan.current_revision_id = revision.revision_id
    await catalog_session.flush()

    answer = await run_chat(
        session=catalog_session, graph=graph_service, llm_gateway=LLMGateway(), learner_id=learner_id,
        message="what should I do this week",
    )
    assert answer.conservative
    assert plan.plan_id in answer.citations or revision.revision_id in answer.citations


async def test_skill_id_hint_drives_concept_explanation_without_keyword_match(catalog_session, graph_service):
    learner_id = await _make_learner(catalog_session)
    answer = await run_chat(
        session=catalog_session, graph=graph_service, llm_gateway=LLMGateway(), learner_id=learner_id,
        message="tell me more", skill_id_hint="skill.chain_rule",
    )
    assert "skill.chain_rule" in answer.citations
