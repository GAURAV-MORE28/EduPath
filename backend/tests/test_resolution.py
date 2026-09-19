"""Misconception resolution tests (`app/assessment/resolution.py`): the
deterministic state machine -- suspected/confirmed -> remediating ->
resolved/persistent -- plus the deterministic `INSERT_REMEDIATION`/
`ADD_PROBE` plan-revision insertion. Against a real (SQLite) session via
`sqlite_session` (`tests/conftest.py`) and a small hand-built graph (mirrors
`tests/test_gap_engine.py`'s `tiny_graph_service` fixture), not the full
curated dataset -- isolates exactly the cooldown/cycle-count logic this
module owns.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.assessment import resolution
from app.db.models import (
    LearnerProfile,
    Misconception,
    PlanItem,
    PlanRevision,
    Resource,
    Role,
    RoleRequirement,
    Skill,
    SkillEdge,
    User,
    WeeklyPlan,
)
from app.graph.loader import GraphLoader
from app.graph.queries import SkillGraphService
from app.repositories.assessment_repository import AssessmentRepository
from app.repositories.catalog_repository import CatalogSnapshot
from app.repositories.planning_repository import PlanningRepository

pytestmark = pytest.mark.asyncio


def _graph_service() -> SkillGraphService:
    snapshot = CatalogSnapshot(
        skills=[
            Skill(skill_id="skill.a", label="A", kind="concept", area="test", aliases=[], description="", assessable=True),
            Skill(skill_id="skill.b", label="B", kind="concept", area="test", aliases=[], description="", assessable=True),
        ],
        skill_edges=[
            SkillEdge(from_skill="skill.a", to_skill="skill.b", type="PREREQUISITE_OF", strength="hard", min_level=1, weight=None, source="curated", reviewed_by="test")
        ],
        roles=[Role(role_id="role.test", title="Test", description="")],
        role_requirements=[RoleRequirement(role_id="role.test", skill_id="skill.b", required_level=2, weight=3)],
        misconceptions=[
            Misconception(
                misconception_id="misc.x", description="desc", skill_id="skill.b", root_skill_id="skill.a",
                signature="sig", severity="high", remediation_candidates=["res.remedy"],
            )
        ],
        resources=[
            Resource(
                resource_id="res.remedy", title="Remedy", url="https://example.org/remedy", provider="test",
                type="article", difficulty=1, duration_min=15, modality="read", prerequisite_skill_ids=[],
                learning_objective_text="", audience="", language="en", cost="free", curation_tier="curated",
                reviewed_by="test", link_status="ok",
            )
        ],
        resource_skills=[],
        practice_items=[],
        graph_meta=None,
    )
    skill_graph = GraphLoader.build(snapshot)
    return SkillGraphService(skill_graph)


async def _make_learner(session) -> str:
    user = User(email_hash="hash")
    session.add(user)
    await session.flush()
    profile = LearnerProfile(user_id=user.user_id, target_role_id="role.test", weekly_hours=5.0, preferences={}, constraints={})
    session.add(profile)
    await session.flush()
    return profile.learner_id


# -- upsert_signal_status --------------------------------------------------------------


async def test_upsert_creates_a_new_row_when_none_exists(sqlite_session):
    repo = AssessmentRepository(sqlite_session)
    learner_id = await _make_learner(sqlite_session)
    lm = await resolution.upsert_signal_status(repo, learner_id=learner_id, misconception_id="misc.x", status="suspected", evidence_ids=["i0"])
    assert lm.status == "suspected"
    assert lm.evidence_ids == ["i0"]


async def test_upsert_advances_suspected_to_confirmed(sqlite_session):
    repo = AssessmentRepository(sqlite_session)
    learner_id = await _make_learner(sqlite_session)
    await resolution.upsert_signal_status(repo, learner_id=learner_id, misconception_id="misc.x", status="suspected", evidence_ids=["i0"])
    lm = await resolution.upsert_signal_status(repo, learner_id=learner_id, misconception_id="misc.x", status="confirmed", evidence_ids=["i1"])
    assert lm.status == "confirmed"
    assert set(lm.evidence_ids) == {"i0", "i1"}


async def test_upsert_never_downgrades_a_remediating_row_back_to_suspected(sqlite_session):
    from app.db.models import LearnerMisconception

    repo = AssessmentRepository(sqlite_session)
    learner_id = await _make_learner(sqlite_session)
    await repo.create_learner_misconception(LearnerMisconception(learner_id=learner_id, misconception_id="misc.x", status="remediating", evidence_ids=[]))
    result = await resolution.upsert_signal_status(repo, learner_id=learner_id, misconception_id="misc.x", status="suspected", evidence_ids=["i2"])
    assert result.status == "remediating"  # unchanged


# -- start_remediation --------------------------------------------------------------


async def test_start_remediation_picks_up_curated_remediation_resources(sqlite_session):
    graph = _graph_service()
    assessment_repo = AssessmentRepository(sqlite_session)
    planning_repo = PlanningRepository(sqlite_session)
    learner_id = await _make_learner(sqlite_session)

    outcome = await resolution.start_remediation(
        repo=assessment_repo, planning_repo=planning_repo, graph=graph, learner_id=learner_id,
        misconception_id="misc.x", skill_id="skill.b", probe_item_ids=["item.probe.1"], evidence_ids=["i0", "i1"],
    )
    assert outcome.started is True
    assert outcome.remediation_resource_ids == ["res.remedy"]
    assert outcome.learner_misconception.status == "remediating"
    assert outcome.plan_revision_id is None  # no active plan yet -- nothing to insert into


async def test_start_remediation_is_a_noop_with_no_active_plan(sqlite_session):
    graph = _graph_service()
    assessment_repo = AssessmentRepository(sqlite_session)
    planning_repo = PlanningRepository(sqlite_session)
    learner_id = await _make_learner(sqlite_session)

    outcome = await resolution.start_remediation(
        repo=assessment_repo, planning_repo=planning_repo, graph=graph, learner_id=learner_id,
        misconception_id="misc.x", skill_id="skill.b", probe_item_ids=[], evidence_ids=[],
    )
    assert outcome.plan_revision_id is None


async def test_start_remediation_inserts_a_new_plan_revision_carrying_forward_prior_items(sqlite_session):
    graph = _graph_service()
    assessment_repo = AssessmentRepository(sqlite_session)
    planning_repo = PlanningRepository(sqlite_session)
    learner_id = await _make_learner(sqlite_session)

    plan = await planning_repo.create_weekly_plan(WeeklyPlan(learner_id=learner_id, week_index=0, hours_budget=5.0, status="committed"))
    revision = await planning_repo.create_revision(
        PlanRevision(plan_id=plan.plan_id, revision_no=1, parent_revision_id=None, cause_type="initial", cause_ref="", operators=[], diff={}, degraded=False, overall_reason="")
    )
    await planning_repo.create_items(
        [PlanItem(plan_id=plan.plan_id, revision_id=revision.revision_id, type="resource", objective_id="obj.1", skill_id="skill.b", est_minutes=20, difficulty=1, day_slot=1, status="planned")]
    )
    plan.current_revision_id = revision.revision_id

    outcome = await resolution.start_remediation(
        repo=assessment_repo, planning_repo=planning_repo, graph=graph, learner_id=learner_id,
        misconception_id="misc.x", skill_id="skill.b", probe_item_ids=["item.probe.1"], evidence_ids=["i0", "i1"],
    )

    assert outcome.plan_revision_id is not None
    new_items = await planning_repo.list_items_for_revision(outcome.plan_revision_id)
    types = {i.type for i in new_items}
    assert "resource" in types  # carried forward from the prior revision
    assert "review" in types  # INSERT_REMEDIATION
    assert "probe" in types  # ADD_PROBE
    review_item = next(i for i in new_items if i.type == "review")
    assert review_item.resource_id == "res.remedy"
    probe_item = next(i for i in new_items if i.type == "probe")
    assert probe_item.practice_item_ids == ["item.probe.1"]

    revisions = await planning_repo.list_revisions(plan.plan_id)
    assert len(revisions) == 2
    assert revisions[-1].cause_type == "remediation"


async def test_start_remediation_skips_a_persistent_misconception(sqlite_session):
    from app.db.models import LearnerMisconception

    graph = _graph_service()
    assessment_repo = AssessmentRepository(sqlite_session)
    planning_repo = PlanningRepository(sqlite_session)
    learner_id = await _make_learner(sqlite_session)
    await assessment_repo.create_learner_misconception(
        LearnerMisconception(learner_id=learner_id, misconception_id="misc.x", status="persistent", remediation_cycles=2, evidence_ids=[])
    )

    outcome = await resolution.start_remediation(
        repo=assessment_repo, planning_repo=planning_repo, graph=graph, learner_id=learner_id,
        misconception_id="misc.x", skill_id="skill.b", probe_item_ids=[], evidence_ids=[],
    )
    assert outcome.started is False
    assert outcome.skip_reason is not None
    assert "persistent" in outcome.skip_reason


async def test_start_remediation_skips_within_cooldown(sqlite_session):
    from app.db.models import LearnerMisconception

    graph = _graph_service()
    assessment_repo = AssessmentRepository(sqlite_session)
    planning_repo = PlanningRepository(sqlite_session)
    learner_id = await _make_learner(sqlite_session)
    await assessment_repo.create_learner_misconception(
        LearnerMisconception(
            learner_id=learner_id, misconception_id="misc.x", status="remediating", evidence_ids=[],
            last_remediated_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
    )

    outcome = await resolution.start_remediation(
        repo=assessment_repo, planning_repo=planning_repo, graph=graph, learner_id=learner_id,
        misconception_id="misc.x", skill_id="skill.b", probe_item_ids=[], evidence_ids=[],
    )
    assert outcome.started is False
    assert "cooldown" in outcome.skip_reason


async def test_start_remediation_proceeds_after_cooldown_expires(sqlite_session):
    from app.db.models import LearnerMisconception

    graph = _graph_service()
    assessment_repo = AssessmentRepository(sqlite_session)
    planning_repo = PlanningRepository(sqlite_session)
    learner_id = await _make_learner(sqlite_session)
    await assessment_repo.create_learner_misconception(
        LearnerMisconception(
            learner_id=learner_id, misconception_id="misc.x", status="remediating", evidence_ids=[],
            last_remediated_at=datetime.now(timezone.utc) - timedelta(hours=25),
        )
    )

    outcome = await resolution.start_remediation(
        repo=assessment_repo, planning_repo=planning_repo, graph=graph, learner_id=learner_id,
        misconception_id="misc.x", skill_id="skill.b", probe_item_ids=[], evidence_ids=[],
    )
    assert outcome.started is True


async def test_start_remediation_handles_an_unknown_misconception_id_gracefully(sqlite_session):
    graph = _graph_service()
    assessment_repo = AssessmentRepository(sqlite_session)
    planning_repo = PlanningRepository(sqlite_session)
    learner_id = await _make_learner(sqlite_session)

    outcome = await resolution.start_remediation(
        repo=assessment_repo, planning_repo=planning_repo, graph=graph, learner_id=learner_id,
        misconception_id="misc.does_not_exist", skill_id="skill.b", probe_item_ids=[], evidence_ids=[],
    )
    assert outcome.started is True
    assert outcome.remediation_resource_ids == []  # no curated remediation, still schedules the probe path


# -- record_probe_result --------------------------------------------------------------


async def test_probe_pass_resolves_the_misconception(sqlite_session):
    from app.db.models import LearnerMisconception

    repo = AssessmentRepository(sqlite_session)
    learner_id = await _make_learner(sqlite_session)
    await repo.create_learner_misconception(LearnerMisconception(learner_id=learner_id, misconception_id="misc.x", status="remediating", evidence_ids=[]))

    lm = await resolution.record_probe_result(repo, learner_id=learner_id, misconception_id="misc.x", passed=True)
    assert lm.status == "resolved"
    assert lm.resolved_at is not None


async def test_probe_fail_starts_a_second_remediation_cycle(sqlite_session):
    from app.db.models import LearnerMisconception

    repo = AssessmentRepository(sqlite_session)
    learner_id = await _make_learner(sqlite_session)
    await repo.create_learner_misconception(LearnerMisconception(learner_id=learner_id, misconception_id="misc.x", status="remediating", remediation_cycles=0, evidence_ids=[]))

    lm = await resolution.record_probe_result(repo, learner_id=learner_id, misconception_id="misc.x", passed=False)
    assert lm.status == "remediating"
    assert lm.remediation_cycles == 1


async def test_two_failed_cycles_becomes_persistent_and_does_not_loop_indefinitely(sqlite_session):
    from app.db.models import LearnerMisconception

    repo = AssessmentRepository(sqlite_session)
    learner_id = await _make_learner(sqlite_session)
    await repo.create_learner_misconception(LearnerMisconception(learner_id=learner_id, misconception_id="misc.x", status="remediating", remediation_cycles=1, evidence_ids=[]))

    lm = await resolution.record_probe_result(repo, learner_id=learner_id, misconception_id="misc.x", passed=False)
    assert lm.status == "persistent"
    assert lm.remediation_cycles == 2


async def test_record_probe_result_raises_for_an_unknown_misconception(sqlite_session):
    repo = AssessmentRepository(sqlite_session)
    learner_id = await _make_learner(sqlite_session)
    with pytest.raises(ValueError):
        await resolution.record_probe_result(repo, learner_id=learner_id, misconception_id="misc.never_seen", passed=True)
