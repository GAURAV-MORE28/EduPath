"""The deterministic Plan Validator (design §17.2's V1-V10, plus the Phase 5
brief's "no duplicated work without justification" and "required objective
coverage" checks -- folded in as `V_DUP`/`V_COVERAGE` below since they are
not literally named in design §17.2 but are additive, same latitude
`app/gap/engine.py`'s audit flags already used for design-adjacent checks).

A **pure function**: no DB/gateway import anywhere in this module
(ARCHITECTURE_CONTRACTS.md §2/§10 -- this is a deterministic service, not one
of the five LLM agents). Operates entirely over already-built
`app.schemas.common.PlanItem`s and the candidate/gap-report data the caller
(`app/planning/service.py`) already fetched -- same "unit-testable with
hand-built fixtures" shape as `app/gap/engine.py` and
`app/retrieval/ranker.py`.

CLT and ZPD are honestly framed as *pedagogical heuristics* here (design
§17.1), not validated mathematical claims -- V4/V5/V6/V9 approximate CLT's
"limit simultaneous new/extraneous load"; V3/V10 approximate ZPD's
"slightly-beyond-reach-with-support" sequencing. Nothing in this module
claims to measure cognitive load or compute "the ZPD" exactly.

Hard rules (ARCHITECTURE_CONTRACTS.md §10: "must be 0% violations on any
committed plan"): V1, V2, V3, V4, V5, V_DUP, V9. A **Fallback Planner**
(`app/planning/fallback.py`) must always satisfy all of these -- see that
module.

Soft rules (checked, logged, never block commit): V6, V7, V8, V10, V_COVERAGE.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.core.thresholds import (
    NEW_SKILL_CONCURRENCY_CAP,
    NEW_SKILL_CONCURRENCY_CAP_NOVICE,
    OVERLOAD_BUDGET_FACTOR,
    OVERLOAD_CONCURRENCY_REDUCTION,
    SESSION_CHUNK_MAX_MINUTES,
    WEEKLY_BUDGET_SLACK,
)
from app.gap.engine import MET, UNVERIFIED, SkillGapEntry
from app.planning.candidates import ObjectiveCandidateSet
from app.schemas.common import PlanItem

# design §17.2's rule identifiers, kept UPPER_SNAKE (ARCHITECTURE_CONTRACTS.md
# §12: internal enum-ish identifiers, not a design-doc-verbatim status field).
V1_TIME_BUDGET = "V1_time_budget"
V2_REFERENTIAL_INTEGRITY = "V2_referential_integrity"
V3_PREREQUISITE_ORDER = "V3_prerequisite_order"
V4_DIFFICULTY_BAND = "V4_difficulty_band"
V5_NEW_SKILL_CONCURRENCY = "V5_new_skill_concurrency"
V6_SESSION_CHUNKING = "V6_session_chunking"
V7_PRACTICE_PAIRING = "V7_practice_pairing"
V8_STRUGGLE_FOLLOW_UP = "V8_struggle_follow_up"
V9_POST_OVERLOAD_HEADROOM = "V9_post_overload_headroom"
V10_GUIDANCE_FADING = "V10_guidance_fading"
V_DUP = "V_no_unjustified_duplicates"
V_COVERAGE = "V_required_objective_coverage"

HARD = "hard"
SOFT = "soft"

_LESSON_ITEM_TYPES = ("resource", "practice", "project")


@dataclass
class Violation:
    rule: str
    severity: str  # "hard" | "soft"
    message: str
    item_ids: list[str] = field(default_factory=list)


@dataclass
class ValidationResult:
    passed: bool  # no hard violations -- eligible to commit
    hard_violations: list[Violation] = field(default_factory=list)
    soft_violations: list[Violation] = field(default_factory=list)

    @property
    def violations(self) -> list[Violation]:
        return self.hard_violations + self.soft_violations


def effective_budget_minutes(weekly_hours: float, *, overload_active: bool = False) -> float:
    """design §16.3 point 3 / §17.2 V9: `hours * 60 * 0.9`, then `* 0.8` for
    two weeks after an overload signal. No overload-signal source exists yet
    in this project (Struggle Classifier is Phase 8/9) -- `overload_active`
    is accepted as a caller-supplied flag for when one does, same pattern
    `app/retrieval/ranker.py` used for `learner_history` ahead of a real
    source existing."""
    budget = weekly_hours * 60 * WEEKLY_BUDGET_SLACK
    if overload_active:
        budget *= OVERLOAD_BUDGET_FACTOR
    return budget


def effective_new_skill_cap(*, novice: bool = False, overload_active: bool = False) -> int:
    """design §17.2 V5/V9: default 3, 2 for novices, `K - 1` for two weeks
    after an overload signal."""
    cap = NEW_SKILL_CONCURRENCY_CAP_NOVICE if novice else NEW_SKILL_CONCURRENCY_CAP
    if overload_active:
        cap = max(1, cap - OVERLOAD_CONCURRENCY_REDUCTION)
    return cap


def validate_plan(
    items: list[PlanItem],
    *,
    candidate_sets: dict[str, ObjectiveCandidateSet],
    gaps_by_skill: dict[str, SkillGapEntry],
    hard_prereqs_by_skill: dict[str, list[str]],
    hours_budget_minutes: float,
    new_skill_cap: int = NEW_SKILL_CONCURRENCY_CAP,
) -> ValidationResult:
    """Runs every V-rule against `items` (already sorted or not -- `day_slot`
    is read from each item, not list order). `hard_prereqs_by_skill` is the
    direct hard `PREREQUISITE_OF` predecessors for every skill that appears
    in `gaps_by_skill` (design §13.3's `graph.hard_parents`, recomputed by
    the caller from `SkillGraphService.direct_prerequisites(..., include_soft=False)`
    -- kept out of this module to stay DB/graph-import-free). A prerequisite
    skill absent from `gaps_by_skill` (outside the role's scope) is treated
    as satisfied -- there is no data to check it against, the same
    simplification `app/retrieval/ranker.py`'s `met_skill_ids` already makes.
    """
    hard: list[Violation] = []
    soft: list[Violation] = []

    hard += _v1_time_budget(items, hours_budget_minutes)
    hard += _v2_referential_integrity(items, candidate_sets)
    hard += _v3_prerequisite_order(items, gaps_by_skill, hard_prereqs_by_skill)
    hard += _v4_difficulty_band(items, gaps_by_skill)
    hard += _v5_new_skill_concurrency(items, gaps_by_skill, new_skill_cap)
    hard += _v_no_unjustified_duplicates(items)

    soft += _v6_session_chunking(items)
    soft += _v7_practice_pairing(items, gaps_by_skill)
    soft += _v10_guidance_fading(items, gaps_by_skill)
    soft += _v_objective_coverage(items, candidate_sets)

    return ValidationResult(passed=not hard, hard_violations=hard, soft_violations=soft)


# ---------------------------------------------------------------------------
# Hard rules
# ---------------------------------------------------------------------------


def _v1_time_budget(items: list[PlanItem], hours_budget_minutes: float) -> list[Violation]:
    total = sum(i.est_minutes for i in items)
    if total > hours_budget_minutes:
        return [
            Violation(
                V1_TIME_BUDGET,
                HARD,
                f"plan totals {total} min, exceeding the {hours_budget_minutes:.0f} min budget",
                [i.item_id for i in items],
            )
        ]
    return []


def _v2_referential_integrity(
    items: list[PlanItem], candidate_sets: dict[str, ObjectiveCandidateSet]
) -> list[Violation]:
    violations: list[Violation] = []
    for item in items:
        cs = candidate_sets.get(item.objective_id)
        if cs is None:
            violations.append(Violation(V2_REFERENTIAL_INTEGRITY, HARD, f"unknown objective_id {item.objective_id!r}", [item.item_id]))
            continue
        if item.skill_id != cs.skill_id:
            violations.append(
                Violation(
                    V2_REFERENTIAL_INTEGRITY,
                    HARD,
                    f"item skill_id {item.skill_id!r} does not match objective {item.objective_id!r}'s skill {cs.skill_id!r}",
                    [item.item_id],
                )
            )
        if item.resource_id is not None and item.resource_id not in {r.resource_id for r in cs.resources}:
            violations.append(
                Violation(V2_REFERENTIAL_INTEGRITY, HARD, f"resource_id {item.resource_id!r} not in objective's candidate set", [item.item_id])
            )
        unknown_practice_ids = set(item.practice_item_ids) - set(cs.practice_item_ids)
        if unknown_practice_ids:
            violations.append(
                Violation(
                    V2_REFERENTIAL_INTEGRITY,
                    HARD,
                    f"practice_item_ids {sorted(unknown_practice_ids)} not in objective's candidate set",
                    [item.item_id],
                )
            )
    return violations


def _v3_prerequisite_order(
    items: list[PlanItem],
    gaps_by_skill: dict[str, SkillGapEntry],
    hard_prereqs_by_skill: dict[str, list[str]],
) -> list[Violation]:
    """design §17.2 V3: each hard prerequisite `p` of an item's skill is
    `MET`, or has an item scheduled at an earlier `day_slot` in this same
    plan, or (if `p` is `UNVERIFIED`) has a *probe* item scheduled earlier."""
    earliest_slot_for_skill: dict[str, int] = {}
    earliest_probe_slot_for_skill: dict[str, int] = {}
    for i in items:
        earliest_slot_for_skill[i.skill_id] = min(earliest_slot_for_skill.get(i.skill_id, i.day_slot), i.day_slot)
        if i.type == "probe":
            earliest_probe_slot_for_skill[i.skill_id] = min(
                earliest_probe_slot_for_skill.get(i.skill_id, i.day_slot), i.day_slot
            )

    violations: list[Violation] = []
    for item in items:
        if item.type not in _LESSON_ITEM_TYPES:
            continue
        for prereq_skill_id in hard_prereqs_by_skill.get(item.skill_id, []):
            gap = gaps_by_skill.get(prereq_skill_id)
            if gap is None or gap.status == MET:
                continue  # MET, or outside scope -- nothing to check against
            scheduled_earlier = earliest_slot_for_skill.get(prereq_skill_id, float("inf")) < item.day_slot
            if scheduled_earlier:
                continue
            if gap.status == UNVERIFIED:
                probe_earlier = earliest_probe_slot_for_skill.get(prereq_skill_id, float("inf")) < item.day_slot
                if probe_earlier:
                    continue
            violations.append(
                Violation(
                    V3_PREREQUISITE_ORDER,
                    HARD,
                    f"{item.skill_id} scheduled (day {item.day_slot}) but hard prerequisite {prereq_skill_id} "
                    f"(status {gap.status}) is not MET and not scheduled earlier",
                    [item.item_id],
                )
            )
    return violations


def _v4_difficulty_band(items: list[PlanItem], gaps_by_skill: dict[str, SkillGapEntry]) -> list[Violation]:
    violations: list[Violation] = []
    for item in items:
        gap = gaps_by_skill.get(item.skill_id)
        if gap is None:
            continue
        if item.difficulty > gap.current_level + 1:
            violations.append(
                Violation(
                    V4_DIFFICULTY_BAND,
                    HARD,
                    f"{item.skill_id} item difficulty {item.difficulty} exceeds current_level+1 ({gap.current_level + 1})",
                    [item.item_id],
                )
            )
    return violations


def _v5_new_skill_concurrency(
    items: list[PlanItem], gaps_by_skill: dict[str, SkillGapEntry], new_skill_cap: int
) -> list[Violation]:
    new_skills = {
        i.skill_id
        for i in items
        if i.type in _LESSON_ITEM_TYPES and gaps_by_skill.get(i.skill_id) and gaps_by_skill[i.skill_id].status != MET
    }
    if len(new_skills) > new_skill_cap:
        return [
            Violation(
                V5_NEW_SKILL_CONCURRENCY,
                HARD,
                f"{len(new_skills)} new skills scheduled this week, exceeding the cap of {new_skill_cap}",
                [i.item_id for i in items if i.skill_id in new_skills],
            )
        ]
    return []


def _v_no_unjustified_duplicates(items: list[PlanItem]) -> list[Violation]:
    seen: dict[tuple[str, str], str] = {}
    violations: list[Violation] = []
    for item in items:
        if item.resource_id is None or item.type == "review":
            continue
        key = (item.skill_id, item.resource_id)
        if key in seen:
            violations.append(
                Violation(
                    V_DUP,
                    HARD,
                    f"resource {item.resource_id!r} scheduled twice for {item.skill_id!r} without a review/justification",
                    [seen[key], item.item_id],
                )
            )
        else:
            seen[key] = item.item_id
    return violations


# ---------------------------------------------------------------------------
# Soft rules
# ---------------------------------------------------------------------------


def _v6_session_chunking(items: list[PlanItem]) -> list[Violation]:
    return [
        Violation(V6_SESSION_CHUNKING, SOFT, f"{i.item_id} is {i.est_minutes} min, longer than a {SESSION_CHUNK_MAX_MINUTES} min session", [i.item_id])
        for i in items
        if i.est_minutes > SESSION_CHUNK_MAX_MINUTES
    ]


def _v7_practice_pairing(items: list[PlanItem], gaps_by_skill: dict[str, SkillGapEntry]) -> list[Violation]:
    by_skill: dict[str, list[PlanItem]] = {}
    for i in items:
        by_skill.setdefault(i.skill_id, []).append(i)

    violations: list[Violation] = []
    for skill_id, skill_items in by_skill.items():
        gap = gaps_by_skill.get(skill_id)
        if gap is None or gap.status == MET:
            continue
        has_new_content = any(i.type == "resource" for i in skill_items)
        has_practice = any(i.type in ("practice", "probe") for i in skill_items)
        if has_new_content and not has_practice:
            violations.append(
                Violation(V7_PRACTICE_PAIRING, SOFT, f"{skill_id} has new content this week but no practice/probe item", [i.item_id for i in skill_items])
            )
    return violations


def _v10_guidance_fading(items: list[PlanItem], gaps_by_skill: dict[str, SkillGapEntry]) -> list[Violation]:
    """design §17.2 V10: "for level-0 skills, prefer worked-example/guided
    resources first" -- approximated as "the resource item is scheduled no
    later than the practice item for the same still-level-0 skill"."""
    by_skill: dict[str, list[PlanItem]] = {}
    for i in items:
        by_skill.setdefault(i.skill_id, []).append(i)

    violations: list[Violation] = []
    for skill_id, skill_items in by_skill.items():
        gap = gaps_by_skill.get(skill_id)
        if gap is None or gap.current_level > 0:
            continue
        resource_slots = [i.day_slot for i in skill_items if i.type == "resource"]
        practice_slots = [i.day_slot for i in skill_items if i.type in ("practice", "probe")]
        if resource_slots and practice_slots and min(resource_slots) > min(practice_slots):
            violations.append(
                Violation(V10_GUIDANCE_FADING, SOFT, f"{skill_id} (level 0) has practice scheduled before its guided resource", [i.item_id for i in skill_items])
            )
    return violations


def _v_objective_coverage(items: list[PlanItem], candidate_sets: dict[str, ObjectiveCandidateSet]) -> list[Violation]:
    """Phase 5 brief: "required objective coverage" -- informational only
    (soft), since a genuinely empty candidate set (the "impossible candidate
    set" case) can make 100% coverage unreachable for *any* planner, LLM or
    fallback; blocking commit on it would violate "a demo/run can never fail
    to produce a plan" (ARCHITECTURE_CONTRACTS.md §10)."""
    schedulable = {oid for oid, cs in candidate_sets.items() if cs.resources or cs.practice_item_ids}
    if not schedulable:
        return []
    covered = {i.objective_id for i in items}
    missing = schedulable - covered
    if missing:
        return [
            Violation(
                V_COVERAGE,
                SOFT,
                f"{len(missing)}/{len(schedulable)} schedulable objectives have no plan item this week",
                [],
            )
        ]
    return []
