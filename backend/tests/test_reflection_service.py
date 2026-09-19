"""End-to-end Reflection tests against the real curated dataset
(`catalog_session` fixture) -- the Phase 9 "wow scenario":

    Chain Rule misunderstanding -> detected -> prerequisite identified ->
    backprop activity deferred -> chain-rule remediation inserted ->
    plan validated -> revision shown.

This replays `data/dataset/demo/demo_scenario.json`'s scripted attempt (the
same backpropagation + chain_rule items, the same misc.chain_rule_sum wrong
answers) through the real pipeline: `submit_practice_set` ->
`classify_struggle` (repeated_misconception confirmed + missing_prerequisite)
-> `app/reflection/service.py::run_reflection` -> root cause `skill.chain_rule`
-> `INSERT_REMEDIATION` + `DEFER` + `ADD_PROBE` (exactly
`demo_scenario.json`'s `expected_reflection_operators`) -> a validated
`PlanRevision` that defers the existing backpropagation item and inserts a
chain_rule remediation + resolution-check probe.
"""
from __future__ import annotations

import pytest

from app.assessment.service import SubmittedAnswer, submit_practice_set
from app.db.models import Evidence, LearnerProfile, LearnerSkillState, PlanItem, PlanRevision, User, WeeklyPlan
from app.gateway.llm_gateway import LLMGateway
from app.graph.loader import GraphLoader
from app.graph.queries import SkillGraphService
from app.repositories.assessment_repository import AssessmentRepository
from app.repositories.catalog_repository import CatalogRepository
from app.repositories.planning_repository import PlanningRepository
from app.repositories.reflection_repository import ReflectionRepository

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def graph_service(catalog_session) -> SkillGraphService:
    skill_graph = await GraphLoader(CatalogRepository(catalog_session)).load()
    return SkillGraphService(skill_graph)


async def _make_learner(session, *, weekly_hours: float = 6.0) -> str:
    user = User(email_hash="hash-reflection")
    session.add(user)
    await session.flush()
    profile = LearnerProfile(user_id=user.user_id, target_role_id="role.ml_engineer", weekly_hours=weekly_hours, preferences={}, constraints={})
    session.add(profile)
    await session.flush()
    return profile.learner_id


async def _seed_met_evidence(session, learner_id: str, skill_id: str) -> None:
    """Strong (E3, high-mastery, n_obs>=3) evidence -- MET at any role-required
    level 1-3 (`app.core.thresholds.LEVEL_MASTERY_THRESHOLD`/`LEVEL_TIER_REQUIRED`)."""
    session.add(Evidence(learner_id=learner_id, skill_id=skill_id, tier="E3", source_type="assessment", verified=True))
    session.add(LearnerSkillState(learner_id=learner_id, skill_id=skill_id, alpha=20.0, beta=1.0, band="proficient", confidence="high", n_obs=5, tier_max="E3"))
    await session.flush()


async def _seed_plan_with_backpropagation_item(session, learner_id: str, graph: SkillGraphService) -> tuple[str, str]:
    """A minimal existing plan (mirrors `tests/test_resolution.py`'s
    hand-built plan) with one `skill.backpropagation` item scheduled at day
    2 -- something for `DEFER` to actually move. Every *other* hard-prerequisite
    ancestor of `skill.backpropagation` (there are ten, several chained --
    `skill.chain_rule` itself is the only one deliberately left alone, since
    it's the gap under test) is seeded straight to MET so
    `V3_prerequisite_order` sees a plan the Plan Validator would actually
    have approved in the first place, without also having to replicate the
    curated graph's full topological depth as extra placeholder items."""
    for ancestor in sorted(graph.hard_ancestors("skill.backpropagation") - {"skill.chain_rule"}):
        await _seed_met_evidence(session, learner_id, ancestor)

    planning_repo = PlanningRepository(session)
    plan = await planning_repo.create_weekly_plan(WeeklyPlan(learner_id=learner_id, week_index=0, hours_budget=6.0, status="committed"))
    revision = await planning_repo.create_revision(
        PlanRevision(plan_id=plan.plan_id, revision_no=1, parent_revision_id=None, cause_type="initial", cause_ref="", operators=[], diff={}, degraded=False, overall_reason="")
    )
    await planning_repo.create_items(
        [
            PlanItem(
                plan_id=plan.plan_id, revision_id=revision.revision_id, type="resource", objective_id="obj.backpropagation",
                skill_id="skill.backpropagation", resource_id=None, est_minutes=30, difficulty=1, day_slot=2, status="planned",
            ),
        ]
    )
    plan.current_revision_id = revision.revision_id
    return plan.plan_id, revision.revision_id


async def test_chain_rule_wow_scenario_end_to_end(catalog_session, graph_service):
    catalog = CatalogRepository(catalog_session)
    assessment_repo = AssessmentRepository(catalog_session)
    reflection_repo = ReflectionRepository(catalog_session)
    learner_id = await _make_learner(catalog_session)
    plan_id, _initial_revision_id = await _seed_plan_with_backpropagation_item(catalog_session, learner_id, graph_service)

    from app.db.models import PracticeSession

    # design §13.4's demo chain: mirrors `data/dataset/demo/demo_scenario.json`'s
    # scripted attempt (backpropagation items + a chain_rule prerequisite block, all
    # wrong, all tagged misc.chain_rule_sum) -- items/indices looked up dynamically
    # (like `tests/test_assessment_integration.py` already does), never hardcoded,
    # so this stays correct if the curated dataset's exact wording/options change.
    backprop_items = await catalog.get_practice_items_for_skill("skill.backpropagation", purpose="practice")
    chain_rule_items = await catalog.get_practice_items_for_skill("skill.chain_rule", purpose="practice")

    def _wrong_tagged(items, *, count):
        chosen = []
        for item in items:
            for idx, option in enumerate(item.options):
                if not option["is_key"] and option["misconception_id"] == "misc.chain_rule_sum":
                    chosen.append((item.item_id, idx))
                    break
            if len(chosen) == count:
                break
        return chosen

    # only one real skill.backpropagation practice item has a *wrong* option
    # tagged misc.chain_rule_sum (its other wrong options carry a different
    # misconception tag) -- combined with 2 tagged skill.chain_rule items,
    # that's still >= REPEATED_MISCONCEPTION_CONFIRM_COUNT tagged occurrences
    # in one submission (the classifier counts across all items, not just
    # the target skill's), while the chain_rule pair also fails the
    # prerequisite-block probe threshold (0/2 correct).
    backprop_chosen = _wrong_tagged(backprop_items, count=1)
    chain_rule_chosen = _wrong_tagged(chain_rule_items, count=2)
    assert len(backprop_chosen) == 1 and len(chain_rule_chosen) == 2

    all_chosen = backprop_chosen + chain_rule_chosen
    item_ids = [iid for iid, _ in all_chosen]
    answers = [SubmittedAnswer(item_id=iid, chosen_option=idx) for iid, idx in all_chosen]

    practice_session = PracticeSession(learner_id=learner_id, skill_id="skill.backpropagation", purpose="practice", item_ids=item_ids)
    await assessment_repo.create_practice_session(practice_session)

    outcome = await submit_practice_set(
        session=catalog_session, graph=graph_service, llm_gateway=LLMGateway(), learner_id=learner_id, set_id=practice_session.set_id,
        answers=answers,
    )

    # -- detected --
    signal_classes = {s.signal_class for s in outcome.signals}
    assert "repeated_misconception" in signal_classes
    assert "missing_prerequisite" in signal_classes
    misconception_signal = next(s for s in outcome.signals if s.signal_class == "repeated_misconception")
    assert misconception_signal.counts["status"] == "confirmed"
    assert misconception_signal.counts["misconception_id"] == "misc.chain_rule_sum"

    # -- prerequisite identified: root cause is skill.chain_rule, an ancestor of skill.backpropagation --
    assert outcome.reflection is not None
    assert outcome.reflection.needs_attention is False
    assert outcome.reflection.root_cause_skill_id == "skill.chain_rule"
    assert outcome.reflection.misconception_id == "misc.chain_rule_sum"
    assert outcome.reflection.misconception_status == "remediating"

    # -- operators match demo_scenario.json's expected_reflection_operators --
    op_names = {op["op"] for op in outcome.reflection.operators}
    assert op_names == {"INSERT_REMEDIATION", "DEFER", "ADD_PROBE"}

    # -- plan validated + revision shown --
    plan_revision_id = outcome.reflection.plan_revision_id
    assert plan_revision_id is not None

    planning_repo = PlanningRepository(catalog_session)
    new_items = await planning_repo.list_items_for_revision(plan_revision_id)
    revisions = await planning_repo.list_revisions(plan_id)
    assert len(revisions) == 2
    assert revisions[-1].revision_id == plan_revision_id
    assert revisions[-1].cause_type == "reflection"

    # backprop activity deferred (still present, pushed later than day 2).
    backprop_items = [i for i in new_items if i.skill_id == "skill.backpropagation"]
    assert len(backprop_items) == 1
    assert backprop_items[0].day_slot > 2

    # chain-rule remediation inserted.
    chain_rule_review = [i for i in new_items if i.skill_id == "skill.chain_rule" and i.type == "review"]
    assert len(chain_rule_review) == 1
    assert chain_rule_review[0].resource_id in {"res.khan_diff_calc", "res.3b1b_calculus", "res.cs231n_backprop"}

    # resolution-check probe on chain_rule -- the curated dataset has no
    # `purpose="resolution-check"` items for skill.chain_rule specifically
    # (only skill.backpropagation.6 has one) and `LLM_PROVIDER=none` means no
    # generation fallback either, so the probe item itself is real but may
    # carry zero practice_item_ids; that gap is pre-existing (design §18.2's
    # bank-first assembly) and unrelated to this pipeline's own correctness.
    chain_rule_probe = [i for i in new_items if i.skill_id == "skill.chain_rule" and i.type == "probe"]
    assert len(chain_rule_probe) == 1

    # -- ReflectionRecord + DecisionRecord written (design §20.9) --
    reflection_id = outcome.reflection.reflection_id
    assert reflection_id is not None
    decisions = await reflection_repo.list_decision_records(learner_id, type_="reflection")
    assert len(decisions) == 1
    assert decisions[0].output_ref == plan_revision_id
    assert decisions[0].graph_paths and decisions[0].graph_paths[0][0] == "skill.chain_rule"
    assert decisions[0].graph_paths[0][-1] == "skill.backpropagation"


async def test_cooldown_prevents_a_second_reflection_within_the_window(catalog_session, graph_service):
    from app.db.models import PracticeSession

    catalog = CatalogRepository(catalog_session)
    assessment_repo = AssessmentRepository(catalog_session)
    learner_id = await _make_learner(catalog_session)
    await _seed_plan_with_backpropagation_item(catalog_session, learner_id, graph_service)

    backprop_items = await catalog.get_practice_items_for_skill("skill.backpropagation", purpose="practice")
    chain_rule_items = await catalog.get_practice_items_for_skill("skill.chain_rule", purpose="practice")

    def _wrong_tagged(items, *, count):
        chosen = []
        for item in items:
            for idx, option in enumerate(item.options):
                if not option["is_key"] and option["misconception_id"] == "misc.chain_rule_sum":
                    chosen.append((item.item_id, idx))
                    break
            if len(chosen) == count:
                break
        return chosen

    all_chosen = _wrong_tagged(backprop_items, count=1) + _wrong_tagged(chain_rule_items, count=2)
    item_ids = [iid for iid, _ in all_chosen]

    async def _submit():
        answers = [SubmittedAnswer(item_id=iid, chosen_option=idx) for iid, idx in all_chosen]
        session_row = PracticeSession(learner_id=learner_id, skill_id="skill.backpropagation", purpose="practice", item_ids=item_ids)
        await assessment_repo.create_practice_session(session_row)
        return await submit_practice_set(
            session=catalog_session, graph=graph_service, llm_gateway=LLMGateway(), learner_id=learner_id, set_id=session_row.set_id,
            answers=answers,
        )

    first = await _submit()
    assert first.reflection is not None
    assert first.reflection.plan_revision_id is not None

    second = await _submit()
    # misc.chain_rule_sum is now `remediating` and within cooldown -- the
    # second identical submission must not trigger a second revision.
    assert second.reflection is None
