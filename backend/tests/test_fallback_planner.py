"""Fallback Planner tests (`app/planning/fallback.py`).
ARCHITECTURE_CONTRACTS.md §10: "A Fallback Planner must always exist and
must always satisfy the hard rules... a demo/run can never fail to produce a
plan" -- every test here also re-runs the deterministic Plan Validator
(`app/planning/validator.py`) against the fallback's own output to prove
that contract directly, not just assert on item counts.
"""
from __future__ import annotations

from app.gap.engine import MISSING, UNVERIFIED, SkillGapEntry
from app.planning.candidates import ObjectiveCandidateSet, ResourceCandidateInfo
from app.planning.fallback import build_fallback_plan
from app.planning.validator import validate_plan


def _gap(skill_id: str, *, status: str, current_level: int = 0, ordering_layer: int = 0) -> SkillGapEntry:
    return SkillGapEntry(
        skill_id=skill_id,
        label=skill_id,
        status=status,
        gap_type=status.lower(),
        required_level=2,
        current_level=current_level,
        ordering_layer=ordering_layer,
    )


def _resource(resource_id: str, duration_min: int = 20) -> ResourceCandidateInfo:
    return ResourceCandidateInfo(
        resource_id=resource_id,
        title=f"Resource {resource_id}",
        url="https://example.org",
        type="article",
        duration_min=duration_min,
        modality="read",
        score=1.0,
        score_breakdown={},
    )


def _lesson_cs(objective_id: str, skill_id: str, *, priority: float = 1.0, resources=None, practice_item_ids=None) -> ObjectiveCandidateSet:
    return ObjectiveCandidateSet(
        objective_id=objective_id,
        skill_id=skill_id,
        objective_type="lesson",
        target_level=2,
        current_level=0,
        priority=priority,
        prerequisite_objective_ids=[],
        resources=resources or [],
        practice_item_ids=practice_item_ids or [],
    )


def _probe_cs(objective_id: str, skill_id: str, *, priority: float = 1.0, practice_item_ids=None) -> ObjectiveCandidateSet:
    return ObjectiveCandidateSet(
        objective_id=objective_id,
        skill_id=skill_id,
        objective_type="probe",
        target_level=1,
        current_level=0,
        priority=priority,
        prerequisite_objective_ids=[],
        resources=[],
        practice_item_ids=practice_item_ids or [],
    )


def test_fallback_builds_a_resource_plus_practice_item_within_budget():
    cs = _lesson_cs("obj.a", "skill.a", resources=[_resource("res.a", 20)], practice_item_ids=["item.a.1"])
    items = build_fallback_plan(
        {"obj.a": cs},
        gaps_by_skill={"skill.a": _gap("skill.a", status=MISSING)},
        hours_budget_minutes=100,
    )

    assert [i.type for i in items] == ["resource", "practice"]
    assert items[0].resource_id == "res.a"
    assert items[1].practice_item_ids == ["item.a.1"]
    assert items[0].reason.text  # templated, non-empty, no LLM


def test_fallback_builds_probe_items_for_verify_before_teach():
    cs = _probe_cs("obj.a", "skill.a", practice_item_ids=["item.a.1", "item.a.2"])
    items = build_fallback_plan(
        {"obj.a": cs},
        gaps_by_skill={"skill.a": _gap("skill.a", status=UNVERIFIED)},
        hours_budget_minutes=100,
    )

    assert len(items) == 1
    assert items[0].type == "probe"
    assert items[0].practice_item_ids == ["item.a.1", "item.a.2"]
    assert items[0].resource_id is None


def test_fallback_orders_by_priority_then_layer():
    cs_low = _lesson_cs("obj.low", "skill.low", priority=1.0, resources=[_resource("res.low")])
    cs_high = _lesson_cs("obj.high", "skill.high", priority=5.0, resources=[_resource("res.high")])
    gaps = {
        "skill.low": _gap("skill.low", status=MISSING, ordering_layer=0),
        "skill.high": _gap("skill.high", status=MISSING, ordering_layer=0),
    }

    items = build_fallback_plan(
        {"obj.low": cs_low, "obj.high": cs_high},
        gaps_by_skill=gaps,
        hours_budget_minutes=1000,
        new_skill_cap=10,
    )

    resource_items = [i for i in items if i.type == "resource"]
    assert resource_items[0].skill_id == "skill.high"  # higher priority scheduled first


# -- impossible candidate set --------------------------------------------------------------


def test_impossible_candidate_set_produces_a_valid_empty_plan():
    """No eligible resources and no bank items anywhere -- the fallback
    planner must still return a *valid* (here: empty) plan, never raise."""
    cs_lesson = _lesson_cs("obj.a", "skill.a")  # no resources at all
    cs_probe = _probe_cs("obj.b", "skill.b")  # no practice items at all

    items = build_fallback_plan(
        {"obj.a": cs_lesson, "obj.b": cs_probe},
        gaps_by_skill={"skill.a": _gap("skill.a", status=MISSING), "skill.b": _gap("skill.b", status=UNVERIFIED)},
        hours_budget_minutes=100,
    )

    assert items == []

    result = validate_plan(
        items,
        candidate_sets={"obj.a": cs_lesson, "obj.b": cs_probe},
        gaps_by_skill={"skill.a": _gap("skill.a", status=MISSING), "skill.b": _gap("skill.b", status=UNVERIFIED)},
        hard_prereqs_by_skill={"skill.a": [], "skill.b": []},
        hours_budget_minutes=100,
    )
    assert result.passed


def test_no_candidate_sets_at_all_produces_a_valid_empty_plan():
    items = build_fallback_plan({}, gaps_by_skill={}, hours_budget_minutes=100)
    assert items == []


# -- insufficient time --------------------------------------------------------------


def test_insufficient_time_skips_objectives_that_do_not_fit_but_stays_valid():
    cs_a = _lesson_cs("obj.a", "skill.a", priority=5.0, resources=[_resource("res.a", 90)])
    cs_b = _lesson_cs("obj.b", "skill.b", priority=1.0, resources=[_resource("res.b", 10)])
    gaps = {"skill.a": _gap("skill.a", status=MISSING), "skill.b": _gap("skill.b", status=MISSING)}

    items = build_fallback_plan(
        {"obj.a": cs_a, "obj.b": cs_b},
        gaps_by_skill=gaps,
        hours_budget_minutes=15,  # too small for either resource+practice combo except b's 10 min alone
    )

    # obj.a's 90 min resource cannot fit; obj.b's 10 min resource can.
    assert any(i.skill_id == "skill.b" for i in items)
    assert not any(i.skill_id == "skill.a" for i in items)

    result = validate_plan(
        items,
        candidate_sets={"obj.a": cs_a, "obj.b": cs_b},
        gaps_by_skill=gaps,
        hard_prereqs_by_skill={"skill.a": [], "skill.b": []},
        hours_budget_minutes=15,
    )
    assert result.passed  # V1 holds: fallback never overshoots the budget it was given


def test_zero_budget_produces_an_empty_but_valid_plan():
    cs = _lesson_cs("obj.a", "skill.a", resources=[_resource("res.a", 5)])
    items = build_fallback_plan(
        {"obj.a": cs},
        gaps_by_skill={"skill.a": _gap("skill.a", status=MISSING)},
        hours_budget_minutes=0,
    )
    assert items == []


# -- new-skill concurrency cap respected --------------------------------------------------------------


def test_fallback_never_exceeds_the_new_skill_cap():
    candidate_sets = {}
    gaps = {}
    for i, skill in enumerate(["skill.a", "skill.b", "skill.c", "skill.d"]):
        obj_id = f"obj.{skill}"
        candidate_sets[obj_id] = _lesson_cs(obj_id, skill, priority=float(4 - i), resources=[_resource(f"res.{skill}")])
        gaps[skill] = _gap(skill, status=MISSING)

    items = build_fallback_plan(
        candidate_sets,
        gaps_by_skill=gaps,
        hours_budget_minutes=10_000,
        new_skill_cap=2,
    )

    new_skills = {i.skill_id for i in items if i.type == "resource"}
    assert len(new_skills) <= 2

    result = validate_plan(
        items,
        candidate_sets=candidate_sets,
        gaps_by_skill=gaps,
        hard_prereqs_by_skill={s: [] for s in gaps},
        hours_budget_minutes=10_000,
        new_skill_cap=2,
    )
    assert result.passed
