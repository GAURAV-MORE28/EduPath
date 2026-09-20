"""`app/tutor/intent.py` -- rule-based intent classification and tool
planning (design §23.1's question-type -> tools table). `plan_tools` is pure
and tested directly; `classify_intent`'s skill-mention matching needs the
real curated catalog (`catalog_session`), same as `tests/test_tutor_tools.py`.
"""
from __future__ import annotations

import uuid

import pytest

from app.core.thresholds import TUTOR_MAX_TOOL_STEPS
from app.db.models import LearnerProfile, User
from app.graph.loader import GraphLoader
from app.graph.queries import SkillGraphService
from app.repositories.catalog_repository import CatalogRepository
from app.tutor.intent import CONCEPT_EXPLANATION, GAPS, OUT_OF_SCOPE, PLAN, PROGRESS, WHY_CHANGED, Intent, classify_intent, plan_tools
from app.tutor.service import build_tutor_context


@pytest.fixture
async def graph_service(catalog_session) -> SkillGraphService:
    skill_graph = await GraphLoader(CatalogRepository(catalog_session)).load()
    return SkillGraphService(skill_graph)


async def _make_learner(session) -> str:
    user = User(email_hash=f"hash-intent-{uuid.uuid4()}")
    session.add(user)
    await session.flush()
    profile = LearnerProfile(user_id=user.user_id, target_role_id="role.ml_engineer", weekly_hours=6.0, preferences={}, constraints={})
    session.add(profile)
    await session.flush()
    return profile.learner_id


@pytest.mark.parametrize(
    "name,expected_tools",
    [
        (PLAN, ["get_current_plan"]),
        (WHY_CHANGED, ["get_revisions"]),
        (PROGRESS, ["get_progress"]),
        (GAPS, ["get_gaps"]),
        (OUT_OF_SCOPE, []),
    ],
)
def test_plan_tools_maps_intent_to_expected_tools(name, expected_tools):
    calls = plan_tools(Intent(name=name))
    assert [c.tool for c in calls] == expected_tools


def test_plan_tools_never_exceeds_max_tool_steps():
    # Even a maximally "loaded" intent (hints for both skill_id and
    # decision_id) never exceeds the design's bounded tool-step ceiling.
    for name in (GAPS, WHY_CHANGED, CONCEPT_EXPLANATION):
        calls = plan_tools(Intent(name=name, skill_id="skill.chain_rule", decision_id="dec_1"))
        assert len(calls) <= TUTOR_MAX_TOOL_STEPS


async def test_classify_intent_out_of_scope_when_nothing_groundable(catalog_session, graph_service):
    learner_id = await _make_learner(catalog_session)
    ctx = await build_tutor_context(catalog_session, graph_service, learner_id)

    intent = await classify_intent(ctx, "what is the meaning of life")
    assert intent.name == OUT_OF_SCOPE


async def test_classify_intent_finds_mentioned_skill_by_label(catalog_session, graph_service):
    learner_id = await _make_learner(catalog_session)
    ctx = await build_tutor_context(catalog_session, graph_service, learner_id)

    skill = ctx.graph.get_skill("skill.chain_rule")
    intent = await classify_intent(ctx, f"Why do I need {skill.label} for my role?")
    assert intent.skill_id == "skill.chain_rule"
    assert intent.name == CONCEPT_EXPLANATION


async def test_classify_intent_skill_id_hint_overrides_text_scan(catalog_session, graph_service):
    learner_id = await _make_learner(catalog_session)
    ctx = await build_tutor_context(catalog_session, graph_service, learner_id)

    intent = await classify_intent(ctx, "why is this useful", skill_id_hint="skill.chain_rule")
    assert intent.skill_id == "skill.chain_rule"
    assert intent.name == CONCEPT_EXPLANATION


async def test_classify_intent_progress_keyword(catalog_session, graph_service):
    learner_id = await _make_learner(catalog_session)
    ctx = await build_tutor_context(catalog_session, graph_service, learner_id)

    intent = await classify_intent(ctx, "How am I doing so far?")
    assert intent.name == PROGRESS
