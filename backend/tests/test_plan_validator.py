"""Plan Validator tests (`app/planning/validator.py`): V1-V10 plus the Phase
5 brief's "no duplicated work without justification" / "required objective
coverage" checks. Pure function over hand-built fixtures -- no DB, no
gateway -- same shape as `tests/test_gap_engine.py`/`tests/test_ranker.py`.
"""
from __future__ import annotations

from app.gap.engine import BLOCKED, MET, MISSING, UNVERIFIED, WEAK, SkillGapEntry
from app.planning.candidates import ObjectiveCandidateSet, ResourceCandidateInfo
from app.planning.validator import (
    V1_TIME_BUDGET,
    V2_REFERENTIAL_INTEGRITY,
    V3_PREREQUISITE_ORDER,
    V4_DIFFICULTY_BAND,
    V5_NEW_SKILL_CONCURRENCY,
    V_DUP,
    effective_budget_minutes,
    effective_new_skill_cap,
    validate_plan,
)
from app.schemas.common import PlanItem, PlanItemReason


def _gap(skill_id: str, *, status: str, current_level: int = 0, required_level: int = 2) -> SkillGapEntry:
    return SkillGapEntry(
        skill_id=skill_id,
        label=skill_id,
        status=status,
        gap_type=status.lower(),
        required_level=required_level,
        current_level=current_level,
    )


def _resource(resource_id: str = "res.a", duration_min: int = 20) -> ResourceCandidateInfo:
    return ResourceCandidateInfo(
        resource_id=resource_id,
        title="Title",
        url="https://example.org",
        type="article",
        duration_min=duration_min,
        modality="read",
        score=1.0,
        score_breakdown={},
    )


def _candidate_set(
    objective_id: str,
    skill_id: str,
    *,
    objective_type: str = "lesson",
    current_level: int = 0,
    target_level: int = 2,
    resources: list[ResourceCandidateInfo] | None = None,
    practice_item_ids: list[str] | None = None,
) -> ObjectiveCandidateSet:
    return ObjectiveCandidateSet(
        objective_id=objective_id,
        skill_id=skill_id,
        objective_type=objective_type,
        target_level=target_level,
        current_level=current_level,
        priority=1.0,
        prerequisite_objective_ids=[],
        resources=resources or [],
        practice_item_ids=practice_item_ids or [],
    )


def _item(
    item_id: str,
    *,
    type: str = "resource",
    objective_id: str,
    skill_id: str,
    resource_id: str | None = None,
    practice_item_ids: list[str] | None = None,
    est_minutes: int = 20,
    difficulty: int = 1,
    day_slot: int = 1,
) -> PlanItem:
    return PlanItem(
        item_id=item_id,
        type=type,
        objective_id=objective_id,
        skill_id=skill_id,
        resource_id=resource_id,
        practice_item_ids=practice_item_ids or [],
        est_minutes=est_minutes,
        difficulty=difficulty,
        day_slot=day_slot,
        depends_on=[],
        reason=PlanItemReason(text="because"),
    )


# -- a valid plan --------------------------------------------------------------


def test_valid_plan_passes_with_no_hard_violations():
    res = _resource()
    cs = _candidate_set("obj.1", "skill.a", resources=[res], practice_item_ids=["item.a.1"])
    item = _item("i1", objective_id="obj.1", skill_id="skill.a", resource_id=res.resource_id, est_minutes=20)
    practice = _item(
        "i2", type="practice", objective_id="obj.1", skill_id="skill.a", practice_item_ids=["item.a.1"], est_minutes=5
    )

    result = validate_plan(
        [item, practice],
        candidate_sets={"obj.1": cs},
        gaps_by_skill={"skill.a": _gap("skill.a", status=MISSING)},
        hard_prereqs_by_skill={"skill.a": []},
        hours_budget_minutes=100,
    )

    assert result.passed
    assert result.hard_violations == []
    assert result.soft_violations == []  # practice is paired, session is short, coverage is full


# -- V1 time budget --------------------------------------------------------------


def test_insufficient_time_budget_is_a_hard_violation():
    res = _resource(duration_min=90)
    cs = _candidate_set("obj.1", "skill.a", resources=[res])
    item = _item("i1", objective_id="obj.1", skill_id="skill.a", resource_id=res.resource_id, est_minutes=90)

    result = validate_plan(
        [item],
        candidate_sets={"obj.1": cs},
        gaps_by_skill={"skill.a": _gap("skill.a", status=MISSING)},
        hard_prereqs_by_skill={"skill.a": []},
        hours_budget_minutes=60,  # 90 min scheduled > 60 min budget
    )

    assert not result.passed
    assert any(v.rule == V1_TIME_BUDGET for v in result.hard_violations)


def test_effective_budget_minutes_applies_slack_and_overload_factor():
    assert effective_budget_minutes(10) == 10 * 60 * 0.9
    assert effective_budget_minutes(10, overload_active=True) == 10 * 60 * 0.9 * 0.8


def test_effective_new_skill_cap_novice_and_overload():
    assert effective_new_skill_cap() == 3
    assert effective_new_skill_cap(novice=True) == 2
    assert effective_new_skill_cap(overload_active=True) == 2


# -- V2 referential integrity --------------------------------------------------------------


def test_unknown_resource_id_is_a_hard_violation():
    cs = _candidate_set("obj.1", "skill.a", resources=[_resource("res.a")])
    item = _item("i1", objective_id="obj.1", skill_id="skill.a", resource_id="res.invented")

    result = validate_plan(
        [item],
        candidate_sets={"obj.1": cs},
        gaps_by_skill={"skill.a": _gap("skill.a", status=MISSING)},
        hard_prereqs_by_skill={"skill.a": []},
        hours_budget_minutes=1000,
    )

    assert not result.passed
    assert any(v.rule == V2_REFERENTIAL_INTEGRITY for v in result.hard_violations)


def test_unknown_objective_id_is_a_hard_violation():
    item = _item("i1", objective_id="obj.ghost", skill_id="skill.a")

    result = validate_plan(
        [item],
        candidate_sets={},
        gaps_by_skill={},
        hard_prereqs_by_skill={},
        hours_budget_minutes=1000,
    )

    assert not result.passed
    assert any(v.rule == V2_REFERENTIAL_INTEGRITY for v in result.hard_violations)


# -- V3 missing / unscheduled prerequisite --------------------------------------------------------------


def test_missing_prerequisite_not_met_and_not_scheduled_is_a_hard_violation():
    cs = _candidate_set("obj.b", "skill.b", resources=[_resource("res.b")])
    item = _item("i1", objective_id="obj.b", skill_id="skill.b", resource_id="res.b", day_slot=1)

    result = validate_plan(
        [item],
        candidate_sets={"obj.b": cs},
        # skill.a (skill.b's hard prerequisite) is WEAK -- not MET, and never scheduled.
        gaps_by_skill={"skill.a": _gap("skill.a", status=WEAK), "skill.b": _gap("skill.b", status=MISSING)},
        hard_prereqs_by_skill={"skill.b": ["skill.a"]},
        hours_budget_minutes=1000,
    )

    assert not result.passed
    assert any(v.rule == V3_PREREQUISITE_ORDER for v in result.hard_violations)


def test_prerequisite_scheduled_earlier_satisfies_v3():
    cs_a = _candidate_set("obj.a", "skill.a", resources=[_resource("res.a")])
    cs_b = _candidate_set("obj.b", "skill.b", resources=[_resource("res.b")])
    item_a = _item("i1", objective_id="obj.a", skill_id="skill.a", resource_id="res.a", day_slot=1)
    item_b = _item("i2", objective_id="obj.b", skill_id="skill.b", resource_id="res.b", day_slot=2)

    result = validate_plan(
        [item_a, item_b],
        candidate_sets={"obj.a": cs_a, "obj.b": cs_b},
        gaps_by_skill={"skill.a": _gap("skill.a", status=WEAK), "skill.b": _gap("skill.b", status=MISSING)},
        hard_prereqs_by_skill={"skill.b": ["skill.a"], "skill.a": []},
        hours_budget_minutes=1000,
    )

    assert not any(v.rule == V3_PREREQUISITE_ORDER for v in result.hard_violations)


def test_unverified_prerequisite_satisfied_by_an_earlier_probe():
    cs_a = _candidate_set("obj.a", "skill.a", objective_type="probe", practice_item_ids=["item.a.1"])
    cs_b = _candidate_set("obj.b", "skill.b", resources=[_resource("res.b")])
    probe = _item("i1", type="probe", objective_id="obj.a", skill_id="skill.a", practice_item_ids=["item.a.1"], day_slot=1)
    lesson = _item("i2", objective_id="obj.b", skill_id="skill.b", resource_id="res.b", day_slot=2)

    result = validate_plan(
        [probe, lesson],
        candidate_sets={"obj.a": cs_a, "obj.b": cs_b},
        gaps_by_skill={"skill.a": _gap("skill.a", status=UNVERIFIED), "skill.b": _gap("skill.b", status=MISSING)},
        hard_prereqs_by_skill={"skill.b": ["skill.a"], "skill.a": []},
        hours_budget_minutes=1000,
    )

    assert not any(v.rule == V3_PREREQUISITE_ORDER for v in result.hard_violations)


def test_out_of_scope_prerequisite_is_treated_as_satisfied():
    """A prerequisite skill absent from gaps_by_skill (outside the role's
    scope) cannot be checked -- treated as satisfied rather than a false
    hard failure (documented simplification, `app/planning/validator.py`)."""
    cs = _candidate_set("obj.b", "skill.b", resources=[_resource("res.b")])
    item = _item("i1", objective_id="obj.b", skill_id="skill.b", resource_id="res.b", day_slot=1)

    result = validate_plan(
        [item],
        candidate_sets={"obj.b": cs},
        gaps_by_skill={"skill.b": _gap("skill.b", status=MISSING)},
        hard_prereqs_by_skill={"skill.b": ["skill.outside_scope"]},
        hours_budget_minutes=1000,
    )

    assert not any(v.rule == V3_PREREQUISITE_ORDER for v in result.hard_violations)


# -- V4 difficulty band --------------------------------------------------------------


def test_difficulty_above_current_level_plus_one_is_a_hard_violation():
    cs = _candidate_set("obj.a", "skill.a", resources=[_resource("res.a")], current_level=0)
    item = _item("i1", objective_id="obj.a", skill_id="skill.a", resource_id="res.a", difficulty=3)

    result = validate_plan(
        [item],
        candidate_sets={"obj.a": cs},
        gaps_by_skill={"skill.a": _gap("skill.a", status=MISSING, current_level=0)},
        hard_prereqs_by_skill={"skill.a": []},
        hours_budget_minutes=1000,
    )

    assert not result.passed
    assert any(v.rule == V4_DIFFICULTY_BAND for v in result.hard_violations)


# -- V5 new-skill concurrency --------------------------------------------------------------


def test_too_many_new_skills_in_one_week_is_a_hard_violation():
    candidate_sets = {}
    items = []
    gaps = {}
    for i, skill in enumerate(["skill.a", "skill.b", "skill.c", "skill.d"]):
        obj_id = f"obj.{skill}"
        candidate_sets[obj_id] = _candidate_set(obj_id, skill, resources=[_resource(f"res.{skill}")])
        items.append(_item(f"i{i}", objective_id=obj_id, skill_id=skill, resource_id=f"res.{skill}", day_slot=i + 1))
        gaps[skill] = _gap(skill, status=MISSING)

    result = validate_plan(
        items,
        candidate_sets=candidate_sets,
        gaps_by_skill=gaps,
        hard_prereqs_by_skill={s: [] for s in gaps},
        hours_budget_minutes=10_000,
        new_skill_cap=3,
    )

    assert not result.passed
    assert any(v.rule == V5_NEW_SKILL_CONCURRENCY for v in result.hard_violations)


def test_probe_items_do_not_count_toward_new_skill_concurrency():
    candidate_sets = {}
    items = []
    gaps = {}
    for i, skill in enumerate(["skill.a", "skill.b", "skill.c"]):
        obj_id = f"obj.{skill}"
        candidate_sets[obj_id] = _candidate_set(obj_id, skill, objective_type="probe", practice_item_ids=[f"item.{skill}.1"])
        items.append(
            _item(f"i{i}", type="probe", objective_id=obj_id, skill_id=skill, practice_item_ids=[f"item.{skill}.1"], day_slot=i + 1)
        )
        gaps[skill] = _gap(skill, status=UNVERIFIED)

    result = validate_plan(
        items,
        candidate_sets=candidate_sets,
        gaps_by_skill=gaps,
        hard_prereqs_by_skill={s: [] for s in gaps},
        hours_budget_minutes=10_000,
        new_skill_cap=1,
    )

    assert not any(v.rule == V5_NEW_SKILL_CONCURRENCY for v in result.hard_violations)


# -- no duplicated work without justification --------------------------------------------------------------


def test_same_resource_scheduled_twice_without_review_is_a_hard_violation():
    cs = _candidate_set("obj.a", "skill.a", resources=[_resource("res.a")])
    item1 = _item("i1", objective_id="obj.a", skill_id="skill.a", resource_id="res.a", day_slot=1)
    item2 = _item("i2", objective_id="obj.a", skill_id="skill.a", resource_id="res.a", day_slot=2)

    result = validate_plan(
        [item1, item2],
        candidate_sets={"obj.a": cs},
        gaps_by_skill={"skill.a": _gap("skill.a", status=MISSING)},
        hard_prereqs_by_skill={"skill.a": []},
        hours_budget_minutes=1000,
    )

    assert not result.passed
    assert any(v.rule == V_DUP for v in result.hard_violations)


def test_review_type_is_exempt_from_the_duplicate_check():
    cs = _candidate_set("obj.a", "skill.a", resources=[_resource("res.a")])
    item1 = _item("i1", objective_id="obj.a", skill_id="skill.a", resource_id="res.a", day_slot=1)
    item2 = _item("i2", type="review", objective_id="obj.a", skill_id="skill.a", resource_id="res.a", day_slot=5)

    result = validate_plan(
        [item1, item2],
        candidate_sets={"obj.a": cs},
        gaps_by_skill={"skill.a": _gap("skill.a", status=MISSING)},
        hard_prereqs_by_skill={"skill.a": []},
        hours_budget_minutes=1000,
    )

    assert not any(v.rule == V_DUP for v in result.hard_violations)


# -- an impossible / empty plan is trivially valid --------------------------------------------------------------


def test_empty_plan_over_empty_candidates_is_trivially_valid():
    result = validate_plan(
        [],
        candidate_sets={},
        gaps_by_skill={},
        hard_prereqs_by_skill={},
        hours_budget_minutes=100,
    )

    assert result.passed
    assert result.hard_violations == []


def test_blocked_gap_status_is_not_treated_as_satisfying_a_prerequisite():
    cs = _candidate_set("obj.b", "skill.b", resources=[_resource("res.b")])
    item = _item("i1", objective_id="obj.b", skill_id="skill.b", resource_id="res.b", day_slot=1)

    result = validate_plan(
        [item],
        candidate_sets={"obj.b": cs},
        gaps_by_skill={"skill.a": _gap("skill.a", status=BLOCKED), "skill.b": _gap("skill.b", status=MISSING)},
        hard_prereqs_by_skill={"skill.b": ["skill.a"]},
        hours_budget_minutes=1000,
    )

    assert not result.passed
    assert any(v.rule == V3_PREREQUISITE_ORDER for v in result.hard_violations)
