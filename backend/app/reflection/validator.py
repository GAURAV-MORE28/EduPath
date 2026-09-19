"""The Reflection Validator (design §20.6) -- deterministic, no LLM. Checks,
in order:

1. `root_cause_skill_id` exists in the curated graph and is the struggling
   skill itself or one of its hard-prerequisite ancestors.
2. Every `evidence_ids` entry exists and belongs to this learner.
3. `root_cause_class` is compatible with the classifier's own signal class
   for this submission -- **on conflict the classifier wins** (design §20.6
   point 3); a mismatch is rejected outright rather than silently
   overridden, so the caller's retry-then-fallback ladder kicks in.
4. Every operator is from the closed set with structurally valid parameters
   (`app.reflection.operators.validate_operator_params`).
5. After applying the operators, the deterministic Plan Validator
   (`app.planning.validator.validate_plan`) reports no hard violations.

A pure function apart from the graph-ancestor lookup (`SkillGraphService` is
itself DB/gateway-free, same "pure over an already-loaded graph" shape
`app/gap/engine.py` and `app/retrieval/ranker.py` already use).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.gap.engine import SkillGapEntry
from app.graph.queries import SkillGraphService, UnknownSkillError
from app.planning.validator import ValidationResult, validate_plan
from app.reflection.draft import ReflectionDraft
from app.reflection.evidence import EvidenceBundle
from app.reflection.operators import ApplyResult, OperatorError, apply_operators, validate_operator_params
from app.schemas.common import PlanItem


@dataclass
class ReflectionValidationResult:
    approved: bool
    reasons: list[str] = field(default_factory=list)
    apply_result: ApplyResult | None = None
    plan_validation: ValidationResult | None = None


def validate_reflection(
    draft: ReflectionDraft,
    bundle: EvidenceBundle,
    *,
    graph: SkillGraphService,
    gaps_by_skill: dict[str, SkillGapEntry],
    hard_prereqs_by_skill: dict[str, list[str]],
    new_skill_cap: int,
) -> ReflectionValidationResult:
    reasons: list[str] = []

    # 1. root cause exists and is connected to the graph (self or ancestor).
    try:
        graph.get_skill(draft.root_cause_skill_id)
        is_self = draft.root_cause_skill_id == bundle.struggling_skill_id
        is_ancestor = draft.root_cause_skill_id in graph.hard_ancestors(bundle.struggling_skill_id)
        if not (is_self or is_ancestor):
            reasons.append(
                f"root_cause_skill_id {draft.root_cause_skill_id!r} is neither {bundle.struggling_skill_id!r} "
                "nor one of its hard-prerequisite ancestors"
            )
    except UnknownSkillError:
        reasons.append(f"root_cause_skill_id {draft.root_cause_skill_id!r} is not a known skill")

    # 2. evidence exists and belongs to this learner.
    unknown_evidence = [e for e in draft.evidence_ids if e not in bundle.learner_assessment_item_ids]
    if unknown_evidence:
        reasons.append(f"evidence_ids not found in this learner's own assessment history: {unknown_evidence}")
    if not draft.evidence_ids:
        reasons.append("evidence_ids is empty -- a reflection must cite something")

    # 2b. evidence supports the struggle signal (overlaps the triggering
    # signal's own evidence, or is otherwise attributable to it).
    signal_evidence = set(bundle.triggering_signal.evidence_ids)
    if signal_evidence and not (set(draft.evidence_ids) & signal_evidence):
        reasons.append("evidence_ids do not overlap the triggering struggle signal's own evidence")

    # 3. class compatible with the classifier -- on conflict, classifier wins.
    if draft.root_cause_class != bundle.triggering_signal.signal_class:
        reasons.append(
            f"root_cause_class {draft.root_cause_class!r} disagrees with the classifier's "
            f"{bundle.triggering_signal.signal_class!r} -- classifier wins"
        )

    # 4. operators from the closed set with valid parameters.
    for operator in draft.operators:
        reasons.extend(validate_operator_params(operator))

    if reasons:
        return ReflectionValidationResult(approved=False, reasons=reasons)

    # 5. resulting plan still satisfies hard constraints.
    try:
        apply_result = apply_operators(bundle.current_plan_items, draft.operators)
    except OperatorError as exc:
        return ReflectionValidationResult(approved=False, reasons=[f"operators could not be applied: {exc}"])

    hard_prereqs_by_skill = dict(hard_prereqs_by_skill)
    for item in apply_result.items:
        hard_prereqs_by_skill.setdefault(item.skill_id, graph.direct_prerequisites(item.skill_id, include_soft=False))

    plan_validation = validate_plan(
        apply_result.items,
        candidate_sets=_permissive_candidate_sets(apply_result.items),
        gaps_by_skill=gaps_by_skill,
        hard_prereqs_by_skill=hard_prereqs_by_skill,
        hours_budget_minutes=bundle.weekly_hours_budget_minutes,
        new_skill_cap=new_skill_cap,
    )
    if not plan_validation.passed:
        return ReflectionValidationResult(
            approved=False,
            reasons=[v.message for v in plan_validation.hard_violations],
            apply_result=apply_result,
            plan_validation=plan_validation,
        )

    return ReflectionValidationResult(approved=True, apply_result=apply_result, plan_validation=plan_validation)


def _permissive_candidate_sets(items: list[PlanItem]):
    """V2 referential integrity (design §17.2) checks every item's
    `resource_id`/`practice_item_ids` against the objective's *original*
    candidate set -- a concept that doesn't apply to a Reflection patch,
    which works directly off already-curated graph/catalog IDs
    (`REMEDIATED_BY` edges, real practice-session item IDs), not a
    Planner-built `ObjectiveCandidateSet`. A permissive stand-in (every
    item's own IDs are "in" its own singleton candidate set) makes V2 a
    no-op here while keeping every other Plan Validator rule (V1, V3-V5,
    V_DUP, the soft rules) fully enforced, unchanged, against the patched
    plan -- see `app/planning/validator.py::_v2_referential_integrity`.
    """
    from app.planning.candidates import ObjectiveCandidateSet, ResourceCandidateInfo

    candidate_sets: dict[str, ObjectiveCandidateSet] = {}
    for item in items:
        cs = candidate_sets.get(item.objective_id)
        resources = list(cs.resources) if cs else []
        practice_ids = list(cs.practice_item_ids) if cs else []
        if item.resource_id is not None and item.resource_id not in {r.resource_id for r in resources}:
            resources.append(
                ResourceCandidateInfo(
                    resource_id=item.resource_id, title="", url="", type="", duration_min=item.est_minutes,
                    modality="", score=0.0, score_breakdown={},
                )
            )
        practice_ids = sorted(set(practice_ids) | set(item.practice_item_ids))
        candidate_sets[item.objective_id] = ObjectiveCandidateSet(
            objective_id=item.objective_id,
            skill_id=item.skill_id,
            objective_type="lesson",
            target_level=item.difficulty,
            current_level=item.difficulty,
            priority=0.0,
            prerequisite_objective_ids=[],
            resources=resources,
            practice_item_ids=practice_ids,
        )
    return candidate_sets
