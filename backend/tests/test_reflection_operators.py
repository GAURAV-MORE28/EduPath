"""`app/reflection/operators.py` -- the closed set of plan-edit operators.
Pure, hand-built `PlanItem` fixtures, same shape `tests/test_plan_validator.py`
already uses for `app/planning/validator.py`.
"""
from __future__ import annotations

import pytest

from app.reflection.operators import (
    CLOSED_OPERATOR_SET,
    OperatorError,
    apply_operators,
    validate_operator_params,
)
from app.schemas.common import PlanItem, PlanItemReason


def _item(item_id: str, *, skill_id: str = "skill.a", type_: str = "resource", day_slot: int = 1, est_minutes: int = 30, status: str = "planned", resource_id: str | None = "res.1") -> PlanItem:
    return PlanItem(
        item_id=item_id, type=type_, objective_id=f"obj.{skill_id}", skill_id=skill_id, resource_id=resource_id,
        practice_item_ids=[], est_minutes=est_minutes, difficulty=1, day_slot=day_slot, depends_on=[],
        reason=PlanItemReason(text="because"), status=status,
    )


def test_closed_set_has_exactly_the_phase_brief_operators():
    assert CLOSED_OPERATOR_SET == {
        "INSERT_REMEDIATION", "DEFER", "REMOVE_DUPLICATE", "REPLACE_RESOURCE", "ADD_PROBE", "SPLIT_ACTIVITY",
    }


def test_unknown_operator_is_rejected():
    errors = validate_operator_params({"op": "REWRITE_EVERYTHING", "params": {}})
    assert errors and "not in the closed operator set" in errors[0]


def test_insert_remediation_adds_a_review_item_at_the_earliest_matching_slot():
    items = [_item("i1", skill_id="skill.b", day_slot=3)]
    result = apply_operators(items, [{"op": "INSERT_REMEDIATION", "params": {"skill_id": "skill.a", "resource_ids": ["res.remedy"]}}])
    inserted = [i for i in result.items if i.skill_id == "skill.a"]
    assert len(inserted) == 1
    assert inserted[0].type == "review"
    assert inserted[0].resource_id == "res.remedy"
    assert inserted[0].day_slot == 1  # no existing skill.a items -- defaults to day 1
    assert result.diff["inserted"] == [inserted[0].item_id]
    # the untouched item is carried forward unchanged.
    assert any(i.item_id == "i1" for i in result.items)


def test_defer_pushes_matching_items_later_and_never_deletes():
    items = [_item("i1", skill_id="skill.a", day_slot=2), _item("i2", skill_id="skill.b", day_slot=1)]
    result = apply_operators(items, [{"op": "DEFER", "params": {"skill_id": "skill.a", "delay_days": 2}}])
    a_item = next(i for i in result.items if i.item_id == "i1")
    b_item = next(i for i in result.items if i.item_id == "i2")
    assert a_item.day_slot == 4
    assert b_item.day_slot == 1  # untouched
    assert len(result.items) == 2  # nothing deleted


def test_defer_caps_at_the_plan_week_max_day_slot():
    items = [_item("i1", skill_id="skill.a", day_slot=4)]
    result = apply_operators(items, [{"op": "DEFER", "params": {"skill_id": "skill.a", "delay_days": 10}}])
    assert result.items[0].day_slot == 5


def test_defer_never_moves_a_done_item():
    items = [_item("i1", skill_id="skill.a", day_slot=1, status="done")]
    result = apply_operators(items, [{"op": "DEFER", "params": {"skill_id": "skill.a", "delay_days": 3}}])
    assert result.items[0].day_slot == 1
    assert result.diff["deferred"] == []


def test_defer_unknown_skill_raises():
    with pytest.raises(OperatorError):
        apply_operators([_item("i1", skill_id="skill.a")], [{"op": "DEFER", "params": {"skill_id": "skill.zzz"}}])


def test_remove_duplicate_drops_the_named_items():
    items = [_item("i1"), _item("i2")]
    result = apply_operators(items, [{"op": "REMOVE_DUPLICATE", "params": {"item_ids": ["i2"]}}])
    assert [i.item_id for i in result.items] == ["i1"]
    assert result.diff["removed"] == ["i2"]


def test_remove_duplicate_unknown_id_raises():
    with pytest.raises(OperatorError):
        apply_operators([_item("i1")], [{"op": "REMOVE_DUPLICATE", "params": {"item_ids": ["nope"]}}])


def test_replace_resource_swaps_only_the_named_item():
    items = [_item("i1", resource_id="res.old"), _item("i2", resource_id="res.old")]
    result = apply_operators(items, [{"op": "REPLACE_RESOURCE", "params": {"item_id": "i1", "new_resource_id": "res.new"}}])
    by_id = {i.item_id: i for i in result.items}
    assert by_id["i1"].resource_id == "res.new"
    assert by_id["i2"].resource_id == "res.old"


def test_add_probe_appends_after_the_current_max_day_slot():
    items = [_item("i1", day_slot=3)]
    result = apply_operators(items, [{"op": "ADD_PROBE", "params": {"skill_id": "skill.a", "purpose": "resolution-check", "practice_item_ids": ["p1", "p2"]}}])
    probe = next(i for i in result.items if i.type == "probe")
    assert probe.day_slot == 4
    assert probe.practice_item_ids == ["p1", "p2"]
    assert probe.resource_id is None


def test_split_activity_produces_two_smaller_chunked_items():
    items = [_item("i1", est_minutes=60, day_slot=2)]
    result = apply_operators(items, [{"op": "SPLIT_ACTIVITY", "params": {"item_id": "i1", "parts": 2}}])
    assert not any(i.item_id == "i1" for i in result.items)
    split = sorted(result.items, key=lambda i: i.day_slot)
    assert len(split) == 2
    assert split[0].est_minutes == 30 and split[1].est_minutes == 30
    assert split[0].day_slot == 2 and split[1].day_slot == 3


def test_split_activity_unknown_item_raises():
    with pytest.raises(OperatorError):
        apply_operators([_item("i1")], [{"op": "SPLIT_ACTIVITY", "params": {"item_id": "nope"}}])


def test_apply_operators_runs_a_full_sequence_in_order():
    items = [_item("i1", skill_id="skill.b", day_slot=1)]
    operators = [
        {"op": "DEFER", "params": {"skill_id": "skill.b", "delay_days": 2}},
        {"op": "INSERT_REMEDIATION", "params": {"skill_id": "skill.a", "resource_ids": ["res.remedy"]}},
        {"op": "ADD_PROBE", "params": {"skill_id": "skill.a", "purpose": "resolution-check", "practice_item_ids": ["p1"]}},
    ]
    result = apply_operators(items, operators)
    types_by_skill = {i.skill_id: i.type for i in result.items}
    assert types_by_skill["skill.b"] == "resource"  # deferred, not removed
    assert "review" in [i.type for i in result.items if i.skill_id == "skill.a"]
    assert "probe" in [i.type for i in result.items if i.skill_id == "skill.a"]
    assert next(i for i in result.items if i.skill_id == "skill.b").day_slot == 3
