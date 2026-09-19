"""The closed set of plan-edit operators (Phase 9 brief: "The Reflection
Agent must NOT rewrite the entire plan freely. It can only output a CLOSED
SET of plan-edit operators"). Six operators, per the brief's explicit list
(a project-specific closed set -- narrower/differently-named than design
§20.5's, which this project's Reflection module supersedes for this phase):

    INSERT_REMEDIATION  -- add prerequisite-focused remediation items
    DEFER               -- push items/a skill's items later (never delete)
    REMOVE_DUPLICATE    -- drop a duplicated item (design §17.2's V_DUP)
    REPLACE_RESOURCE    -- swap an item's resource (design §20.5's SWAP_RESOURCE)
    ADD_PROBE           -- add a verification/resolution-check item
    SPLIT_ACTIVITY      -- break one long item into smaller chunked sessions

Each operator is a **deterministic function on the plan** (design §20.5):
`apply_operators` is a pure function (no DB/gateway import), operating on
`app.schemas.common.PlanItem` so its output can be re-validated directly by
the existing `app.planning.validator.validate_plan` -- the same
"unit-testable with hand-built fixtures" shape as that module and
`app/gap/engine.py`. Untouched items are carried forward unchanged (design
§20.7: "revisions apply to future items only"); nothing is ever silently
dropped except via an explicit `REMOVE_DUPLICATE`.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from app.core.thresholds import PLAN_WEEK_MAX_DAY_SLOT, REFLECTION_DEFER_DAYS
from app.schemas.common import PlanItem, PlanItemReason

OP_INSERT_REMEDIATION = "INSERT_REMEDIATION"
OP_DEFER = "DEFER"
OP_REMOVE_DUPLICATE = "REMOVE_DUPLICATE"
OP_REPLACE_RESOURCE = "REPLACE_RESOURCE"
OP_ADD_PROBE = "ADD_PROBE"
OP_SPLIT_ACTIVITY = "SPLIT_ACTIVITY"

CLOSED_OPERATOR_SET = frozenset(
    {OP_INSERT_REMEDIATION, OP_DEFER, OP_REMOVE_DUPLICATE, OP_REPLACE_RESOURCE, OP_ADD_PROBE, OP_SPLIT_ACTIVITY}
)


class OperatorError(Exception):
    """Raised for an operator outside the closed set, missing/invalid
    parameters, or a parameter that doesn't refer to anything in the current
    plan -- never applied partially; `apply_operators` raises before
    mutating anything further once one operator fails."""


@dataclass
class ApplyResult:
    items: list[PlanItem]
    diff: dict[str, Any] = field(default_factory=dict)  # {"inserted": [...], "deferred": [...], "removed": [...], "replaced": [...], "split": [...]}


def validate_operator_params(operator: dict[str, Any]) -> list[str]:
    """Structural pre-check (design §20.6 check 4: "operators are from the
    closed set with valid parameters"). Returns a list of error strings
    (empty = OK) -- never raises, so a validator can collect every problem
    across a whole operator list before rejecting."""
    op = operator.get("op")
    params = operator.get("params") or {}
    errors: list[str] = []

    if op not in CLOSED_OPERATOR_SET:
        return [f"{op!r} is not in the closed operator set {sorted(CLOSED_OPERATOR_SET)}"]
    if not isinstance(params, dict):
        return [f"{op}: params must be an object"]

    if op == OP_INSERT_REMEDIATION:
        if not params.get("skill_id"):
            errors.append(f"{op}: missing skill_id")
        if not isinstance(params.get("resource_ids", []), list):
            errors.append(f"{op}: resource_ids must be a list")
    elif op == OP_DEFER:
        if not params.get("skill_id") and not params.get("item_ids"):
            errors.append(f"{op}: needs skill_id or item_ids")
    elif op == OP_REMOVE_DUPLICATE:
        item_ids = params.get("item_ids")
        if not isinstance(item_ids, list) or len(item_ids) < 1:
            errors.append(f"{op}: item_ids must be a non-empty list")
    elif op == OP_REPLACE_RESOURCE:
        if not params.get("item_id"):
            errors.append(f"{op}: missing item_id")
        if not params.get("new_resource_id"):
            errors.append(f"{op}: missing new_resource_id")
    elif op == OP_ADD_PROBE:
        if not params.get("skill_id"):
            errors.append(f"{op}: missing skill_id")
        if not isinstance(params.get("practice_item_ids", []), list):
            errors.append(f"{op}: practice_item_ids must be a list")
    elif op == OP_SPLIT_ACTIVITY:
        if not params.get("item_id"):
            errors.append(f"{op}: missing item_id")
    return errors


def apply_operators(items: list[PlanItem], operators: list[dict[str, Any]]) -> ApplyResult:
    """Applies every operator in order to a copy of `items`. Raises
    `OperatorError` on the first structurally-invalid or unresolvable
    operator -- the caller (the Reflection Validator) is expected to have
    already run `validate_operator_params` over the whole list first, but
    this is re-checked here too since this function must be safe to call on
    its own (e.g. the deterministic fallback path)."""
    current = list(items)
    diff: dict[str, list[Any]] = {"inserted": [], "deferred": [], "removed": [], "replaced": [], "split": []}

    for operator in operators:
        errors = validate_operator_params(operator)
        if errors:
            raise OperatorError("; ".join(errors))
        op = operator["op"]
        params = operator.get("params") or {}

        if op == OP_INSERT_REMEDIATION:
            current, inserted = _insert_remediation(current, params)
            diff["inserted"].extend(inserted)
        elif op == OP_DEFER:
            current, deferred = _defer(current, params)
            diff["deferred"].extend(deferred)
        elif op == OP_REMOVE_DUPLICATE:
            current, removed = _remove_duplicate(current, params)
            diff["removed"].extend(removed)
        elif op == OP_REPLACE_RESOURCE:
            current, replaced = _replace_resource(current, params)
            diff["replaced"].extend(replaced)
        elif op == OP_ADD_PROBE:
            current, inserted = _add_probe(current, params)
            diff["inserted"].extend(inserted)
        elif op == OP_SPLIT_ACTIVITY:
            current, split = _split_activity(current, params)
            diff["split"].extend(split)

    return ApplyResult(items=current, diff=diff)


def _max_day_slot(items: list[PlanItem]) -> int:
    return max((i.day_slot for i in items), default=1)


def _insert_remediation(items: list[PlanItem], params: dict[str, Any]) -> tuple[list[PlanItem], list[str]]:
    skill_id = params["skill_id"]
    resource_ids = list(params.get("resource_ids") or [])
    mode = params.get("mode", "guided")
    est_minutes = int(params.get("est_minutes", 20))

    # design §20.5: "worked-example-first for novices" -- schedule the
    # remediation at the *earliest* slot already touching this skill this
    # week (or day 1 if the skill has no items yet), so it lands before
    # whatever else this skill's deferred/dependent items are pushed to.
    same_skill_slots = [i.day_slot for i in items if i.skill_id == skill_id]
    day_slot = min(same_skill_slots) if same_skill_slots else 1

    inserted_ids: list[str] = []
    new_items = list(items)
    for resource_id in resource_ids[:2] or [None]:
        item_id = str(uuid.uuid4())
        new_items.append(
            PlanItem(
                item_id=item_id,
                type="review",
                objective_id=f"reflection.remediation.{skill_id}",
                skill_id=skill_id,
                resource_id=resource_id,
                practice_item_ids=[],
                est_minutes=est_minutes,
                difficulty=1,
                day_slot=day_slot,
                depends_on=[],
                reason=PlanItemReason(text=f"Remediation ({mode}) inserted for {skill_id} by Reflection."),
                status="planned",
            )
        )
        inserted_ids.append(item_id)
    return new_items, inserted_ids


def _defer(items: list[PlanItem], params: dict[str, Any]) -> tuple[list[PlanItem], list[str]]:
    skill_id = params.get("skill_id")
    explicit_ids = set(params.get("item_ids") or [])
    delay_days = int(params.get("delay_days", REFLECTION_DEFER_DAYS))

    deferred_ids: list[str] = []
    new_items: list[PlanItem] = []
    for item in items:
        matches = (skill_id is not None and item.skill_id == skill_id) or item.item_id in explicit_ids
        if matches and item.status != "done":
            new_day_slot = min(item.day_slot + delay_days, PLAN_WEEK_MAX_DAY_SLOT)
            item = item.model_copy(update={"day_slot": new_day_slot})
            deferred_ids.append(item.item_id)
        new_items.append(item)
    if skill_id is not None and not any(i.skill_id == skill_id for i in items) and not explicit_ids:
        raise OperatorError(f"DEFER: no items found for skill_id {skill_id!r}")
    return new_items, deferred_ids


def _remove_duplicate(items: list[PlanItem], params: dict[str, Any]) -> tuple[list[PlanItem], list[str]]:
    to_remove = set(params["item_ids"])
    missing = to_remove - {i.item_id for i in items}
    if missing:
        raise OperatorError(f"REMOVE_DUPLICATE: unknown item_ids {sorted(missing)}")
    kept = [i for i in items if i.item_id not in to_remove]
    return kept, sorted(to_remove)


def _replace_resource(items: list[PlanItem], params: dict[str, Any]) -> tuple[list[PlanItem], list[str]]:
    item_id = params["item_id"]
    new_resource_id = params["new_resource_id"]
    new_items: list[PlanItem] = []
    found = False
    for item in items:
        if item.item_id == item_id:
            found = True
            item = item.model_copy(update={"resource_id": new_resource_id})
        new_items.append(item)
    if not found:
        raise OperatorError(f"REPLACE_RESOURCE: unknown item_id {item_id!r}")
    return new_items, [item_id]


def _add_probe(items: list[PlanItem], params: dict[str, Any]) -> tuple[list[PlanItem], list[str]]:
    skill_id = params["skill_id"]
    purpose = params.get("purpose", "verification")
    practice_item_ids = list(params.get("practice_item_ids") or [])
    day_slot = min(_max_day_slot(items) + 1, PLAN_WEEK_MAX_DAY_SLOT)

    item_id = str(uuid.uuid4())
    new_items = list(items) + [
        PlanItem(
            item_id=item_id,
            type="probe",
            objective_id=f"reflection.probe.{skill_id}",
            skill_id=skill_id,
            resource_id=None,
            practice_item_ids=practice_item_ids,
            est_minutes=max(1, len(practice_item_ids)) * 3,
            difficulty=1,
            day_slot=day_slot,
            depends_on=[],
            reason=PlanItemReason(text=f"{purpose.capitalize()} probe for {skill_id}, added by Reflection."),
            status="planned",
        )
    ]
    return new_items, [item_id]


def _split_activity(items: list[PlanItem], params: dict[str, Any]) -> tuple[list[PlanItem], list[str]]:
    item_id = params["item_id"]
    parts = max(2, int(params.get("parts", 2)))

    target = next((i for i in items if i.item_id == item_id), None)
    if target is None:
        raise OperatorError(f"SPLIT_ACTIVITY: unknown item_id {item_id!r}")

    per_part_minutes = max(1, target.est_minutes // parts)
    new_ids: list[str] = []
    split_items: list[PlanItem] = []
    for part_index in range(parts):
        new_id = str(uuid.uuid4())
        new_ids.append(new_id)
        split_items.append(
            target.model_copy(
                update={
                    "item_id": new_id,
                    "est_minutes": per_part_minutes,
                    "day_slot": min(target.day_slot + part_index, PLAN_WEEK_MAX_DAY_SLOT),
                    "reason": PlanItemReason(
                        text=f"{target.reason.text} (part {part_index + 1}/{parts}, split by Reflection for session length).".strip(),
                        evidence_ids=target.reason.evidence_ids,
                        graph_path=target.reason.graph_path,
                        decision_id=target.reason.decision_id,
                    ),
                }
            )
        )
    new_items = [i for i in items if i.item_id != item_id] + split_items
    return new_items, new_ids
