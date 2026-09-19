"""End-to-end Practice & Assessment tests against the real curated dataset
(`catalog_session` fixture, `tests/conftest.py`) -- item-bank assembly ->
grading -> mastery update -> struggle classification -> deterministic
remediation, exercising `app/assessment/service.py` with real
`skill.chain_rule` items tagged to the real `misc.chain_rule_sum`
misconception (design §13.4's demo chain). `LLM_PROVIDER=none` (this
project's default) means item generation degrades gracefully (the bank is
used as-is) throughout. Same "regression check on the domain pack itself"
role `tests/test_gap_engine.py`'s `graph_service` fixture plays.
"""
from __future__ import annotations

import pytest

from app.agents.assessor import AssessorAgent
from app.assessment.item_bank import assemble_practice_set
from app.assessment.service import SubmittedAnswer, submit_practice_set
from app.db.models import LearnerProfile, PracticeSession, User
from app.gateway.llm_gateway import LLMGateway
from app.graph.loader import GraphLoader
from app.graph.queries import SkillGraphService
from app.repositories.assessment_repository import AssessmentRepository
from app.repositories.catalog_repository import CatalogRepository

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def graph_service(catalog_session) -> SkillGraphService:
    skill_graph = await GraphLoader(CatalogRepository(catalog_session)).load()
    return SkillGraphService(skill_graph)


async def _make_learner(session, role_id: str = "role.ml_engineer") -> str:
    user = User(email_hash="hash-assessment")
    session.add(user)
    await session.flush()
    profile = LearnerProfile(user_id=user.user_id, target_role_id=role_id, weekly_hours=6.0, preferences={}, constraints={})
    session.add(profile)
    await session.flush()
    return profile.learner_id


async def test_item_bank_assembly_uses_real_chain_rule_items_and_degrades_generation_gracefully(catalog_session, graph_service):
    catalog = CatalogRepository(catalog_session)
    assessor_agent = AssessorAgent(LLMGateway())  # LLM_PROVIDER=none -> degrades

    assembled = await assemble_practice_set(
        catalog=catalog, graph=graph_service, assessor_agent=assessor_agent, skill_id="skill.chain_rule",
        current_level=0, purpose="practice",
    )
    assert assembled.item_ids  # real bank items exist for this skill
    items = await catalog.get_practice_items_by_ids(assembled.item_ids)
    assert all(i.skill_id == "skill.chain_rule" for i in items)
    assert all(i.purpose == "practice" for i in items)


async def test_confirmed_misconception_triggers_deterministic_remediation_with_real_resources(catalog_session, graph_service):
    catalog = CatalogRepository(catalog_session)
    assessment_repo = AssessmentRepository(catalog_session)
    learner_id = await _make_learner(catalog_session)

    tagged_items = await catalog.get_practice_items_for_skill("skill.chain_rule", purpose="practice")
    # find >= 2 distinct items with an option tagged misc.chain_rule_sum, and that option's index --
    # looked up dynamically, never hardcoded, so this stays correct if the dataset changes.
    chosen: list[tuple[str, int]] = []
    for item in tagged_items:
        for idx, option in enumerate(item.options):
            # must be a *wrong* option carrying the tag -- design §18.3/`grade_mcq`
            # never trust a misconception tag on the key, even if curated data has one.
            if not option.get("is_key") and option.get("misconception_id") == "misc.chain_rule_sum":
                chosen.append((item.item_id, idx))
                break
        if len(chosen) == 2:
            break
    assert len(chosen) == 2, "expected >= 2 real skill.chain_rule items tagged with misc.chain_rule_sum"

    practice_session = PracticeSession(learner_id=learner_id, skill_id="skill.chain_rule", purpose="practice", item_ids=[iid for iid, _ in chosen])
    await assessment_repo.create_practice_session(practice_session)

    outcome = await submit_practice_set(
        session=catalog_session, graph=graph_service, llm_gateway=LLMGateway(), learner_id=learner_id, set_id=practice_session.set_id,
        answers=[SubmittedAnswer(item_id=iid, chosen_option=idx) for iid, idx in chosen],
    )

    assert outcome.score == 0.0  # both chosen options were the tagged wrong answers
    assert all(item["misconception_id"] == "misc.chain_rule_sum" for item in outcome.items)

    signal_classes = {s.signal_class for s in outcome.signals}
    assert "repeated_misconception" in signal_classes
    assert "low_score" not in signal_classes  # only 2 items submitted -- below LOW_SCORE_MIN_ITEMS (3), so it can't fire

    assert outcome.reflection is not None
    assert outcome.reflection.needs_attention is False
    assert outcome.reflection.misconception_status == "remediating"
    assert outcome.reflection.root_cause_skill_id == "skill.chain_rule"  # misc.chain_rule_sum's ROOTED_IN skill
    # misc.chain_rule_sum's curated remediation_candidates (data/scripts/build_dataset.py)
    assert set(outcome.reflection.remediation_resource_ids) & {"res.khan_diff_calc", "res.3b1b_calculus", "res.cs231n_backprop"}
    op_names = {op["op"] for op in outcome.reflection.operators}
    assert {"INSERT_REMEDIATION", "ADD_PROBE"} <= op_names
    # root cause == the struggling skill itself here (chain_rule items were submitted
    # directly) -- nothing to defer.
    assert "DEFER" not in op_names


async def test_correct_answers_never_trigger_remediation(catalog_session, graph_service):
    catalog = CatalogRepository(catalog_session)
    assessment_repo = AssessmentRepository(catalog_session)
    learner_id = await _make_learner(catalog_session)

    items = await catalog.get_practice_items_for_skill("skill.chain_rule", purpose="practice")
    item = items[0]
    key_index = next(i for i, o in enumerate(item.options) if o["is_key"])

    practice_session = PracticeSession(learner_id=learner_id, skill_id="skill.chain_rule", purpose="practice", item_ids=[item.item_id])
    await assessment_repo.create_practice_session(practice_session)

    outcome = await submit_practice_set(
        session=catalog_session, graph=graph_service, llm_gateway=LLMGateway(), learner_id=learner_id, set_id=practice_session.set_id,
        answers=[SubmittedAnswer(item_id=item.item_id, chosen_option=key_index)],
    )
    assert outcome.score == 1.0
    assert outcome.signals == []
    assert outcome.reflection is None


async def test_mastery_updates_the_real_learner_skill_state(catalog_session, graph_service):
    from app.repositories.profiling_repository import ProfilingRepository

    catalog = CatalogRepository(catalog_session)
    assessment_repo = AssessmentRepository(catalog_session)
    profiling_repo = ProfilingRepository(catalog_session)
    learner_id = await _make_learner(catalog_session)

    items = await catalog.get_practice_items_for_skill("skill.chain_rule", purpose="practice")
    item = items[0]
    key_index = next(i for i, o in enumerate(item.options) if o["is_key"])

    practice_session = PracticeSession(learner_id=learner_id, skill_id="skill.chain_rule", purpose="practice", item_ids=[item.item_id])
    await assessment_repo.create_practice_session(practice_session)

    assert await profiling_repo.get_learner_skill_state(learner_id, "skill.chain_rule") is None

    await submit_practice_set(
        session=catalog_session, graph=graph_service, llm_gateway=LLMGateway(), learner_id=learner_id, set_id=practice_session.set_id,
        answers=[SubmittedAnswer(item_id=item.item_id, chosen_option=key_index)],
    )

    state = await profiling_repo.get_learner_skill_state(learner_id, "skill.chain_rule")
    assert state is not None
    assert state.tier_max == "E3"
    assert state.n_obs == 1
    assert state.alpha > 1.0  # moved off the uninformative prior
