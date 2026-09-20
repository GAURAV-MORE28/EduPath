"""Deterministic budget-utilization helpers (Stage 2): the pieces both the Fallback Planner and the LLM path share so a plan
uses a large weekly budget with *real, ordered* material instead of stopping after one resource per objective.

Pure module (no DB/gateway/LLM), same shape as `app/planning/validator.py`. Nothing here invents an ID: every session it adds is
taken from an `ObjectiveCandidateSet` (built once, before any model call, by `app/planning/candidates.py`) and every result is
re-checked by `app/planning/validator.py` by the caller before it can become state.

Acceptable utilization, not maximal utilization: `extend_plan` never adds a session that would take the plan above
`target_utilization` of the effective budget (so a later Reflection revision keeps headroom), never pads with material outside the objectives already in the plan, never adds a new skill (so V5 cannot be
affected), never schedules a session out of order, and never exceeds the budget (V1).
"""
from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field

from app.core.thresholds import PLAN_MAX_RESOURCES_PER_OBJECTIVE, PLAN_TARGET_UTILIZATION
from app.gap.engine import SkillGapEntry
from app.planning.candidates import ObjectiveCandidateSet, ResourceCandidateInfo
from app.planning.sessions import ResourceSession, session_meta
from app.schemas.common import PlanItem, PlanItemReason, PlanItemSession

DEFAULT_NUM_DAYS = 5


def plan_item_session(sess: ResourceSession) -> PlanItemSession:
    return PlanItemSession(**session_meta(sess).__dict__)


def difficulty_for(cs: ObjectiveCandidateSet) -> int:
    # design §17.2 V4: difficulty <= current_level(skill) + 1.
    return max(1, min(cs.target_level, cs.current_level + 1))


@dataclass
class DayPlanner:
    """Spreads minutes over `num_days` day slots: an item goes on the earliest day, no earlier than `not_before`, whose load is
    still below `day_cap_minutes` (the last day if none is). A day therefore fills to the cap (overshooting by at most one item)
    before the next one starts, which keeps a chain of sessions in study order (`not_before` = the previous session's day) without
    stacking a whole week on one day. The cap is an even split of the plan's *target* minutes, so a small plan spreads out too."""

    hours_budget_minutes: float
    num_days: int = DEFAULT_NUM_DAYS
    target_utilization: float = PLAN_TARGET_UTILIZATION
    load: dict[int, int] = field(default_factory=dict)

    @property
    def day_cap_minutes(self) -> int:
        return max(1, math.ceil(self.target_utilization * self.hours_budget_minutes / self.num_days))

    @classmethod
    def from_items(
        cls,
        items: list[PlanItem],
        *,
        hours_budget_minutes: float,
        num_days: int = DEFAULT_NUM_DAYS,
        target_utilization: float = PLAN_TARGET_UTILIZATION,
    ) -> "DayPlanner":
        planner = cls(hours_budget_minutes=hours_budget_minutes, num_days=num_days, target_utilization=target_utilization)
        for i in items:
            planner.load[i.day_slot] = planner.load.get(i.day_slot, 0) + i.est_minutes
        return planner

    def place(self, minutes: int, *, not_before: int = 1) -> int:
        start = min(max(1, not_before), self.num_days)
        chosen = self.num_days
        for day in range(start, self.num_days + 1):
            if self.load.get(day, 0) < self.day_cap_minutes:
                chosen = day
                break
        self.load[chosen] = self.load.get(chosen, 0) + minutes
        return chosen


def session_item(
    cs: ObjectiveCandidateSet,
    res: ResourceCandidateInfo,
    sess: ResourceSession,
    *,
    item_id: str,
    day_slot: int,
    reason_text: str,
    depends_on: list[str] | None = None,
) -> PlanItem:
    return PlanItem(
        item_id=item_id,
        type="resource",
        objective_id=cs.objective_id,
        skill_id=cs.skill_id,
        resource_id=res.resource_id,
        practice_item_ids=[],
        est_minutes=sess.est_minutes,
        difficulty=difficulty_for(cs),
        day_slot=day_slot,
        depends_on=depends_on or [],
        reason=PlanItemReason(text=reason_text),
        session=plan_item_session(sess),
    )


def scheduled_session_ids(items: list[PlanItem]) -> set[str]:
    return {i.session.session_id for i in items if i.session is not None}


def _chain_queue(
    cs: ObjectiveCandidateSet,
    items: list[PlanItem],
    used_resource_ids: set[str],
    max_resources: int,
) -> list[tuple[ResourceCandidateInfo, ResourceSession]]:
    """The sessions this objective may still add, in study order: first the unscheduled rest of every resource it has already
    started (in the order they were scheduled), then whole further resources in ranked order -- capped at `max_resources`
    distinct resources per objective. A resource already used through a session-less (legacy) item is treated as finished, and a
    resource used by a *different* objective is skipped (no duplicated learning)."""
    scheduled = scheduled_session_ids(items)
    mine = [i for i in items if i.objective_id == cs.objective_id and i.type == "resource" and i.resource_id]
    started: list[str] = []
    for i in mine:
        if i.resource_id not in started:
            started.append(i.resource_id)
    finished_legacy = {i.resource_id for i in mine if i.session is None}

    queue: list[tuple[ResourceCandidateInfo, ResourceSession]] = []
    for rid in started:
        res = cs.resource(rid)
        if res is None or rid in finished_legacy:
            continue
        queue.extend((res, s) for s in res.sessions if s.session_id not in scheduled)
    distinct = len(started)
    for res in cs.resources:
        if distinct >= max_resources:
            break
        if res.resource_id in started or res.resource_id in used_resource_ids:
            continue
        queue.extend((res, s) for s in res.sessions if s.session_id not in scheduled)
        distinct += 1
    return queue


def extend_plan(
    items: list[PlanItem],
    candidate_sets: dict[str, ObjectiveCandidateSet],
    *,
    hours_budget_minutes: float,
    target_utilization: float = PLAN_TARGET_UTILIZATION,
    max_resources_per_objective: int = PLAN_MAX_RESOURCES_PER_OBJECTIVE,
    num_days: int = DEFAULT_NUM_DAYS,
    new_item_id=None,
) -> list[PlanItem]:
    """Continuation sessions to append to `items` (returns only the *new* items; `items` is not modified).

    Round-robin over the objectives that already have a resource item (highest priority first), one next session per turn, until the
    plan cannot take another session without exceeding `target_utilization * hours_budget_minutes`. Only objectives already in the plan are
    extended, so the set of skills -- and therefore V5 and every prerequisite relationship -- is unchanged."""
    make_id = new_item_id or (lambda: str(uuid.uuid4()))
    total = sum(i.est_minutes for i in items)
    target_minutes = target_utilization * hours_budget_minutes
    if total >= target_minutes:
        return []

    objective_ids = sorted(
        {i.objective_id for i in items if i.type == "resource" and i.resource_id and i.objective_id in candidate_sets},
        key=lambda oid: (-candidate_sets[oid].priority, oid),
    )
    used_resource_ids = {i.resource_id for i in items if i.resource_id}
    queues = {oid: _chain_queue(candidate_sets[oid], items, used_resource_ids - _own(items, oid), max_resources_per_objective) for oid in objective_ids}

    planner = DayPlanner.from_items(
        items, hours_budget_minutes=hours_budget_minutes, num_days=num_days, target_utilization=target_utilization
    )
    last_item: dict[str, PlanItem] = {}  # per objective: the latest resource item in its chain
    for i in items:
        if i.type == "resource" and i.resource_id:
            prev = last_item.get(i.objective_id)
            if prev is None or (i.day_slot, i.session.index if i.session else 0) >= (prev.day_slot, prev.session.index if prev.session else 0):
                last_item[i.objective_id] = i

    new_items: list[PlanItem] = []
    exhausted: set[str] = set()
    progressed = True
    while progressed and total < target_minutes:
        progressed = False
        for oid in objective_ids:
            if total >= target_minutes:
                break
            queue = queues[oid]
            if oid in exhausted or not queue:
                continue
            res, sess = queue[0]
            if total + sess.est_minutes > target_minutes:
                exhausted.add(oid)  # sessions must stay in order, so a session that does not fit ends this objective's chain
                continue
            queue.pop(0)
            prev = last_item.get(oid)
            day = planner.place(sess.est_minutes, not_before=prev.day_slot if prev else 1)
            item = session_item(
                candidate_sets[oid],
                res,
                sess,
                item_id=make_id(),
                day_slot=day,
                depends_on=[prev.item_id] if prev is not None else [],
                reason_text=f"{sess.label} -- next study session for objective {oid}, added to use the remaining weekly time.",
            )
            new_items.append(item)
            last_item[oid] = item
            total += sess.est_minutes
            progressed = True
    return new_items


def _own(items: list[PlanItem], objective_id: str) -> set[str]:
    return {i.resource_id for i in items if i.objective_id == objective_id and i.resource_id}


def attach_reason_provenance(
    items: list[PlanItem],
    *,
    gaps_by_skill: dict[str, SkillGapEntry],
    hard_prereqs_by_skill: dict[str, list[str]],
) -> list[PlanItem]:
    """design §16.6: "the IDs are attached deterministically" -- the LLM only phrases `reason.text`. For each item: `evidence_ids` =
    the Gap Engine's evidence ids for the skill, `graph_path` = the in-scope direct hard prerequisite skills followed by the skill
    itself. Both come from the gap report and the skill graph, never from a model. An LLM-supplied value is never trusted here:
    the fields are overwritten, and `decision_id` is left as it was."""
    out: list[PlanItem] = []
    for item in items:
        gap = gaps_by_skill.get(item.skill_id)
        prereqs = [p for p in hard_prereqs_by_skill.get(item.skill_id, []) if p in gaps_by_skill]
        reason = item.reason.model_copy(
            update={
                "evidence_ids": list(gap.evidence_ids) if gap is not None else [],
                "graph_path": [*prereqs, item.skill_id],
            }
        )
        out.append(item.model_copy(update={"reason": reason}))
    return out


@dataclass(frozen=True)
class UtilizationSummary:
    scheduled_minutes: int
    budget_minutes: float
    utilization: float
    unscheduled_available_minutes: int  # in-order continuation material for objectives already in the plan that would still fit


def summarize_utilization(
    items: list[PlanItem],
    candidate_sets: dict[str, ObjectiveCandidateSet],
    *,
    hours_budget_minutes: float,
    max_resources_per_objective: int = PLAN_MAX_RESOURCES_PER_OBJECTIVE,
    target_utilization: float = PLAN_TARGET_UTILIZATION,
) -> UtilizationSummary:
    total = sum(i.est_minutes for i in items)
    used_resource_ids = {i.resource_id for i in items if i.resource_id}
    headroom = target_utilization * hours_budget_minutes - total
    available = 0
    for oid in {i.objective_id for i in items if i.type == "resource" and i.resource_id and i.objective_id in candidate_sets}:
        for _res, sess in _chain_queue(candidate_sets[oid], items, used_resource_ids - _own(items, oid), max_resources_per_objective):
            if sess.est_minutes > headroom - available:
                break
            available += sess.est_minutes
    return UtilizationSummary(
        scheduled_minutes=total,
        budget_minutes=hours_budget_minutes,
        utilization=(total / hours_budget_minutes) if hours_budget_minutes > 0 else 0.0,
        unscheduled_available_minutes=available,
    )
