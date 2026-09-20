"""Reflection orchestration glue (design §20's pipeline end to end, this
project's Phase 9 -- design's "Phase 8"): assemble evidence -> Reflection
Agent (or its deterministic stand-in, since `LLM_PROVIDER=none` is this
project's permanent default) -> Reflection Validator -> commit
`PlanRevision` + `ReflectionRecord` + `DecisionRecord`, bounded by a
round/cooldown/fallback ladder so a struggle submission can never leave the
plan half-applied (design §20.7's failure behavior).

Mirrors `app/assessment/resolution.py`'s and `app/planning/service.py`'s
split between "pure algorithm" (`app/reflection/{operators,deterministic,
validator}.py`) and "DB/gateway glue" (this module). `app/assessment/resolution.py`
itself is untouched and still owns misconception probe-result bookkeeping
(`record_probe_result`) -- this module calls into it for the state-machine
helpers it already got right, rather than duplicating them.
"""
from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.sse.trace import emit
from app.agents.reflection import ReflectionAgent
from app.assessment import resolution
from app.assessment.struggle import (
    COGNITIVE_OVERLOAD,
    EXCESSIVE_DIFFICULTY,
    MISSING_PREREQUISITE,
    REPEATED_MISCONCEPTION,
    StruggleSignalEntry,
    primary_signal,
)
from app.core.thresholds import NEW_SKILL_CONCURRENCY_CAP, REFLECTION_MAX_ROUNDS, REFLECTION_REVISION_COOLDOWN_HOURS
from app.db.models import DecisionRecord as DecisionRecordRow
from app.db.models import PlanItem as PlanItemRow
from app.db.models import PlanRevision as PlanRevisionRow
from app.db.models import ReflectionRecord as ReflectionRecordRow
from app.gap.engine import GapAnalysisResult, SkillGapEntry
from app.gateway.llm_gateway import LLMGateway
from app.graph.queries import SkillGraphService, UnknownSkillError
from app.reflection.deterministic import RootCauseDecision, build_deterministic_draft, deterministic_root_cause
from app.reflection.draft import ReflectionDraft
from app.reflection.evidence import EvidenceBundle
from app.reflection.operators import OP_ADD_PROBE, OP_INSERT_REMEDIATION
from app.reflection.validator import ReflectionValidationResult, validate_reflection
from app.repositories.assessment_repository import AssessmentRepository
from app.repositories.assessment_repository import within_cooldown as misconception_within_cooldown
from app.repositories.catalog_repository import CatalogRepository
from app.repositories.planning_repository import PlanningRepository
from app.repositories.reflection_repository import ReflectionRepository
from app.repositories.reflection_repository import within_cooldown as reflection_within_cooldown
from app.schemas.common import PlanItem, PlanItemReason, WeeklyPlan

# design §20.2's trigger set (mapped onto this project's `app.assessment.struggle`
# class names): {misconception_confirmed, prerequisite_gap, difficulty_mismatch,
# overload}. `insufficient_practice`/`low_score` are explicitly excluded --
# design §19.3: "Low score... Not by itself a reflection trigger."
TRIGGER_CLASSES = (REPEATED_MISCONCEPTION, MISSING_PREREQUISITE, EXCESSIVE_DIFFICULTY, COGNITIVE_OVERLOAD)


class UnknownRevisionError(Exception):
    pass


@dataclass
class ReflectionOutcome:
    triggered: bool
    skip_reason: str | None = None
    root_cause_skill_id: str | None = None
    root_cause_class: str | None = None
    misconception_id: str | None = None
    misconception_status: str | None = None
    remediation_resource_ids: list[str] = field(default_factory=list)
    operators: list[dict] = field(default_factory=list)
    plan_revision_id: str | None = None
    reflection_id: str | None = None
    decision_id: str | None = None
    degraded: bool = False
    needs_attention: bool = False
    rounds: int = 0
    explanation: str = ""


def pick_trigger(signals: list[StruggleSignalEntry]) -> StruggleSignalEntry | None:
    """design §20.2's trigger classes only, at design's action precedence
    (`app.assessment.struggle.STRUGGLE_ACTION_PRECEDENCE`, unaffected by
    restricting the candidate pool first)."""
    return primary_signal([s for s in signals if s.signal_class in TRIGGER_CLASSES])


async def run_reflection(
    *,
    session: AsyncSession,
    graph: SkillGraphService,
    llm_gateway: LLMGateway,
    learner_id: str,
    signals: list[StruggleSignalEntry],
    gap_result: GapAnalysisResult | None,
    weekly_hours_budget_minutes: float,
) -> ReflectionOutcome:
    trigger = pick_trigger(signals)
    if trigger is None:
        return ReflectionOutcome(triggered=False, skip_reason="no reflection-triggering signal")
    if trigger.signal_class == REPEATED_MISCONCEPTION and trigger.counts.get("status") != "confirmed":
        return ReflectionOutcome(triggered=False, skip_reason="misconception only suspected, not confirmed")
    if gap_result is None:
        return ReflectionOutcome(triggered=False, skip_reason="no gap analysis available for this learner")

    struggling_skill_id = trigger.skill_id
    assessment_repo = AssessmentRepository(session)
    planning_repo = PlanningRepository(session)
    reflection_repo = ReflectionRepository(session)
    catalog = CatalogRepository(session)

    misconception_id = trigger.counts.get("misconception_id") if trigger.signal_class == REPEATED_MISCONCEPTION else None
    misconception_root_skill_id: str | None = None
    lm = None
    if misconception_id:
        misconception = await catalog.get_misconception(misconception_id)
        misconception_root_skill_id = misconception.root_skill_id if misconception else None
        lm = await assessment_repo.get_learner_misconception(learner_id, misconception_id)
        if lm is not None and lm.status == resolution.PERSISTENT:
            return ReflectionOutcome(triggered=False, skip_reason="misconception persistent -- escalated, not re-remediated")
        if lm is not None and lm.status == resolution.REMEDIATING and misconception_within_cooldown(
            lm.last_remediated_at, cooldown_hours=REFLECTION_REVISION_COOLDOWN_HOURS
        ):
            return ReflectionOutcome(triggered=False, skip_reason="cooldown active")
    else:
        last_at = await reflection_repo.last_reflection_at_for_skill(learner_id, struggling_skill_id)
        if reflection_within_cooldown(last_at, cooldown_hours=REFLECTION_REVISION_COOLDOWN_HOURS):
            return ReflectionOutcome(triggered=False, skip_reason="cooldown active")

    plan_row = await planning_repo.get_current_plan_for_learner(learner_id)
    current_items: list[PlanItem] = []
    if plan_row is not None and plan_row.current_revision_id is not None:
        current_items = [_row_to_schema(r) for r in await planning_repo.list_items_for_revision(plan_row.current_revision_id)]

    gaps_by_skill: dict[str, SkillGapEntry] = {g.skill_id: g for g in gap_result.gaps}
    hard_prereqs_by_skill = {s: graph.direct_prerequisites(s, include_soft=False) for s in gaps_by_skill}
    ancestor_statuses = {
        a: gaps_by_skill[a].status for a in graph.hard_ancestors(struggling_skill_id) if a in gaps_by_skill
    }
    learner_item_ids = await assessment_repo.all_assessment_item_ids_for_learner(learner_id)

    bundle = EvidenceBundle(
        learner_id=learner_id,
        struggling_skill_id=struggling_skill_id,
        triggering_signal=trigger,
        all_signals=signals,
        misconception_id=misconception_id,
        misconception_root_skill_id=misconception_root_skill_id,
        ancestor_statuses=ancestor_statuses,
        graph_version=graph.graph_version,
        current_plan_items=current_items,
        learner_assessment_item_ids=learner_item_ids,
        weekly_hours_budget_minutes=weekly_hours_budget_minutes,
    )

    root_cause = deterministic_root_cause(bundle)
    await emit(
        "Reflection Agent", "reflection",
        f"Root cause: {root_cause.skill_id.removeprefix('skill.')} ({root_cause.root_cause_class.replace('_', ' ')})",
        refs=[root_cause.skill_id],
    )
    remediation_resource_ids = _resolve_remediation_resources(graph, root_cause)
    probe_item_ids, probe_purpose = [], _probe_purpose(root_cause)
    if probe_purpose is not None:
        from app.assessment.service import create_practice_session  # local import -- breaks the service<->service cycle

        probe_session = await create_practice_session(
            session=session, graph=graph, llm_gateway=llm_gateway, learner_id=learner_id,
            skill_id=root_cause.skill_id, purpose=probe_purpose, misconception_id=root_cause.misconception_id,
        )
        probe_item_ids = probe_session.item_ids

    split_item_id = _pick_split_item(root_cause, current_items, struggling_skill_id)
    deterministic_draft = build_deterministic_draft(
        bundle, root_cause,
        remediation_resource_ids=remediation_resource_ids,
        probe_practice_item_ids=probe_item_ids,
        split_item_id=split_item_id,
    )

    new_skill_cap = NEW_SKILL_CONCURRENCY_CAP

    def _validate(draft: ReflectionDraft) -> ReflectionValidationResult:
        return validate_reflection(
            draft, bundle, graph=graph, gaps_by_skill=gaps_by_skill,
            hard_prereqs_by_skill=hard_prereqs_by_skill, new_skill_cap=new_skill_cap,
        )

    approved_draft, approved_validation, rounds, from_llm = await _try_agent_rounds(
        llm_gateway=llm_gateway, bundle=bundle, root_cause=root_cause,
        remediation_resource_ids=remediation_resource_ids, probe_item_ids=probe_item_ids, validate=_validate,
    )

    if approved_draft is None:
        validation = _validate(deterministic_draft)
        if validation.approved:
            approved_draft, approved_validation = deterministic_draft, validation
        elif root_cause.misconception_id:
            minimal_draft = _minimal_misconception_draft(root_cause, remediation_resource_ids, probe_item_ids)
            validation = _validate(minimal_draft)
            if validation.approved:
                approved_draft, approved_validation = minimal_draft, validation

    if approved_draft is None or approved_validation is None or approved_validation.apply_result is None:
        reflection_row = await reflection_repo.create_reflection_record(
            ReflectionRecordRow(
                learner_id=learner_id, signal_id=trigger.signal_id, result=asdict(deterministic_draft),
                validated=False, rounds=rounds, degraded=True,
            )
        )
        return ReflectionOutcome(
            triggered=True, root_cause_skill_id=root_cause.skill_id, root_cause_class=root_cause.root_cause_class,
            misconception_id=root_cause.misconception_id, remediation_resource_ids=remediation_resource_ids,
            operators=deterministic_draft.operators, degraded=True, needs_attention=True, rounds=rounds,
            reflection_id=reflection_row.reflection_id,
            explanation="Automatic re-planning could not produce a plan that satisfies hard constraints; the plan was left unchanged.",
        )

    op_names = ", ".join(sorted({str(o.get("op") or o.get("operator") or "?") for o in approved_draft.operators})) or "none"
    await emit("Planner", "replan", f"Applying {op_names}")
    await emit("Plan Validator", "validation", "Revision valid: hard constraints hold")
    plan_revision_id: str | None = None
    if plan_row is not None and plan_row.current_revision_id is not None:
        prior_revisions = await planning_repo.list_revisions(plan_row.plan_id)
        revision = await planning_repo.create_revision(
            PlanRevisionRow(
                plan_id=plan_row.plan_id, revision_no=len(prior_revisions) + 1,
                parent_revision_id=plan_row.current_revision_id, cause_type="reflection",
                cause_ref=f"signal:{trigger.signal_id}", operators=approved_draft.operators,
                diff=approved_validation.apply_result.diff, degraded=not from_llm,
                overall_reason=approved_draft.learner_explanation_draft,
            )
        )
        item_rows = [_schema_to_row(i, plan_id=plan_row.plan_id, revision_id=revision.revision_id) for i in approved_validation.apply_result.items]
        await planning_repo.create_items(item_rows)
        plan_row.current_revision_id = revision.revision_id
        plan_revision_id = revision.revision_id

    misconception_status: str | None = None
    if root_cause.misconception_id:
        lm = await resolution.upsert_signal_status(
            assessment_repo, learner_id=learner_id, misconception_id=root_cause.misconception_id,
            status=resolution.CONFIRMED, evidence_ids=approved_draft.evidence_ids,
        )
        lm.status = resolution.REMEDIATING
        lm.last_remediated_at = datetime.now(timezone.utc)
        misconception_status = lm.status

    reflection_row = await reflection_repo.create_reflection_record(
        ReflectionRecordRow(
            learner_id=learner_id, signal_id=trigger.signal_id, result=asdict(approved_draft),
            validated=True, rounds=rounds, degraded=not from_llm, plan_revision_id=plan_revision_id,
        )
    )
    graph_path = None
    if root_cause.skill_id != struggling_skill_id:
        graph_path = graph.shortest_prerequisite_path(root_cause.skill_id, struggling_skill_id)
    rules_fired = [v.rule for v in approved_validation.plan_validation.violations] if approved_validation.plan_validation else []
    decision_row = await reflection_repo.create_decision_record(
        DecisionRecordRow(
            learner_id=learner_id, type="reflection",
            inputs={"struggling_skill_id": struggling_skill_id, "signal_class": trigger.signal_class, "signal_id": trigger.signal_id},
            evidence_ids=approved_draft.evidence_ids,
            graph_paths=[[s.skill_id for s in graph_path]] if graph_path else [],
            rules_fired=rules_fired, scores={}, llm_run_id=None, graph_version=graph.graph_version,
            output_ref=plan_revision_id or "",
        )
    )
    await emit(
        "Reflection Agent", "decision",
        f"Recorded decision for {struggling_skill_id.removeprefix('skill.')} ({'agent' if from_llm else 'deterministic'} path)",
        refs=[struggling_skill_id, root_cause.skill_id],
        input_ref=trigger.signal_id, output_ref=plan_revision_id or "", decision_id=decision_row.decision_id,
        status="ok" if from_llm else "degraded",
    )

    return ReflectionOutcome(
        triggered=True, root_cause_skill_id=root_cause.skill_id, root_cause_class=root_cause.root_cause_class,
        misconception_id=root_cause.misconception_id, misconception_status=misconception_status,
        remediation_resource_ids=remediation_resource_ids, operators=approved_draft.operators,
        plan_revision_id=plan_revision_id, reflection_id=reflection_row.reflection_id, decision_id=decision_row.decision_id,
        degraded=not from_llm, needs_attention=False, rounds=rounds, explanation=approved_draft.learner_explanation_draft,
    )


async def _try_agent_rounds(
    *, llm_gateway, bundle, root_cause, remediation_resource_ids, probe_item_ids, validate
) -> tuple[ReflectionDraft | None, ReflectionValidationResult | None, int, bool]:
    """The (in this environment never live, since `LLM_PROVIDER=none` is the
    permanent default -- see `app/reflection/deterministic.py`'s module
    docstring) real-LLM round loop. Returns `(None, None, rounds, False)`
    immediately once the gateway reports `degraded` -- deterministic,
    won't change on retry, same as the Planner Agent's own round loop."""
    agent = ReflectionAgent(llm_gateway)
    candidate_root_cause_skill_ids = sorted({bundle.struggling_skill_id, root_cause.skill_id})
    validation_feedback: list[str] | None = None
    rounds = 0
    for round_no in range(REFLECTION_MAX_ROUNDS):
        rounds = round_no + 1
        result = await agent.run(
            str(uuid.uuid4()),
            {
                "bundle": bundle,
                "candidate_root_cause_skill_ids": candidate_root_cause_skill_ids,
                "candidate_resource_ids": remediation_resource_ids,
                "candidate_probe_item_ids": probe_item_ids,
                "validation_feedback": validation_feedback,
            },
        )
        if result["degraded"]:
            return None, None, rounds, False
        candidate_draft: ReflectionDraft = result["draft"]
        validation = validate(candidate_draft)
        if validation.approved:
            return candidate_draft, validation, rounds, True
        validation_feedback = validation.reasons
    return None, None, rounds, False


def _resolve_remediation_resources(graph: SkillGraphService, root_cause: RootCauseDecision) -> list[str]:
    if root_cause.misconception_id:
        try:
            return graph.remediation_resources_for_misconception(root_cause.misconception_id)
        except ValueError:
            return []
    try:
        return graph.resources_targeting(root_cause.skill_id)[:3]
    except UnknownSkillError:
        return []


def _probe_purpose(root_cause: RootCauseDecision) -> str | None:
    if root_cause.root_cause_class in (REPEATED_MISCONCEPTION, MISSING_PREREQUISITE):
        return "resolution-check" if root_cause.misconception_id else "probe"
    if root_cause.root_cause_class == EXCESSIVE_DIFFICULTY:
        return "probe"
    return None  # COGNITIVE_OVERLOAD -- relief, not verification


def _pick_split_item(root_cause: RootCauseDecision, current_items: list[PlanItem], struggling_skill_id: str) -> str | None:
    if root_cause.root_cause_class != EXCESSIVE_DIFFICULTY:
        return None
    candidates = [
        i for i in current_items
        if i.skill_id == struggling_skill_id and i.type in ("resource", "practice", "project") and i.status != "done"
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda i: i.est_minutes).item_id


def _minimal_misconception_draft(
    root_cause: RootCauseDecision, remediation_resource_ids: list[str], probe_item_ids: list[str]
) -> ReflectionDraft:
    """The guaranteed-safe last resort (design §20.6: "failure -> ... ->
    deterministic patch"): `app/assessment/resolution.py`'s original,
    narrower recipe -- `INSERT_REMEDIATION` + `ADD_PROBE` only, no `DEFER` --
    tried only when the richer deterministic draft (which also defers the
    struggling skill's items) itself fails hard validation."""
    return ReflectionDraft(
        root_cause_class=root_cause.root_cause_class,
        root_cause_skill_id=root_cause.skill_id,
        misconception_id=root_cause.misconception_id,
        evidence_ids=root_cause.evidence_ids,
        hypothesis=root_cause.hypothesis,
        confidence=root_cause.confidence,
        path_decision="patch",
        operators=[
            {"op": OP_INSERT_REMEDIATION, "params": {"skill_id": root_cause.skill_id, "resource_ids": remediation_resource_ids[:1]}},
            {"op": OP_ADD_PROBE, "params": {"skill_id": root_cause.skill_id, "purpose": "resolution-check", "practice_item_ids": probe_item_ids}},
        ],
        learner_explanation_draft=f"We added a short remediation on {root_cause.skill_id} and a follow-up check.",
    )


def _row_to_schema(row: PlanItemRow) -> PlanItem:
    return PlanItem(
        item_id=row.item_id, type=row.type, objective_id=row.objective_id, skill_id=row.skill_id,
        resource_id=row.resource_id, practice_item_ids=row.practice_item_ids, est_minutes=row.est_minutes,
        difficulty=row.difficulty, day_slot=row.day_slot, depends_on=row.depends_on,
        reason=PlanItemReason(**row.reason) if row.reason else PlanItemReason(), status=row.status,
    )


def _schema_to_row(item: PlanItem, *, plan_id: str, revision_id: str) -> PlanItemRow:
    """Deliberately does **not** carry `item.item_id` forward -- `item_id` is
    a global primary key (`plan_items.item_id`), not scoped per revision, so
    an item carried forward unchanged from a prior revision (design §20.7)
    needs a fresh one here, exactly like `app/assessment/resolution.py`'s own
    `_apply_remediation_to_plan` already does for the same reason."""
    return PlanItemRow(
        plan_id=plan_id, revision_id=revision_id, type=item.type, objective_id=item.objective_id,
        skill_id=item.skill_id, resource_id=item.resource_id, practice_item_ids=item.practice_item_ids,
        est_minutes=item.est_minutes, difficulty=item.difficulty, day_slot=item.day_slot, depends_on=item.depends_on,
        reason=item.reason.model_dump(mode="json"), status=item.status,
    )


async def revert_to_previous_revision(*, session: AsyncSession, learner_id: str, plan_id: str, revision_id: str) -> WeeklyPlan:
    """design §20.7: "One-click Revert creates a new revision that restores
    the prior content (history stays linear and auditable)." Reverts
    `revision_id` specifically (not just "the current one") back to its own
    `parent_revision_id`'s content -- the learner can undo one specific
    reflection-triggered change even if newer revisions have since landed,
    as long as `revision_id` is still the plan's current revision (reverting
    a superseded revision would silently discard whatever came after it,
    so that is rejected instead)."""
    planning_repo = PlanningRepository(session)
    plan_row = await planning_repo.get_plan(plan_id)
    if plan_row is None or plan_row.learner_id != learner_id:
        raise UnknownRevisionError(f"unknown plan_id {plan_id!r} for this learner")
    if plan_row.current_revision_id != revision_id:
        raise UnknownRevisionError("only the plan's current revision can be reverted")

    bad_revision = await planning_repo.get_revision(revision_id)
    if bad_revision is None or bad_revision.plan_id != plan_id:
        raise UnknownRevisionError(f"unknown revision_id {revision_id!r} for this plan")
    if bad_revision.parent_revision_id is None:
        raise UnknownRevisionError("this is the plan's first revision -- nothing to revert to")

    restore_from = await planning_repo.get_revision(bad_revision.parent_revision_id)
    if restore_from is None:
        raise UnknownRevisionError(f"parent revision {bad_revision.parent_revision_id!r} no longer exists")
    restore_items = await planning_repo.list_items_for_revision(restore_from.revision_id)

    prior_revisions = await planning_repo.list_revisions(plan_id)
    new_revision = await planning_repo.create_revision(
        PlanRevisionRow(
            plan_id=plan_id, revision_no=len(prior_revisions) + 1, parent_revision_id=revision_id,
            cause_type="user_override", cause_ref=f"revert:{revision_id}",
            operators=[], diff={"reverted_revision_id": revision_id, "restored_from_revision_id": restore_from.revision_id},
            degraded=False,
            overall_reason=f"Reverted revision {bad_revision.revision_no} back to revision {restore_from.revision_no}'s content.",
        )
    )
    new_items = [
        PlanItemRow(
            plan_id=plan_id, revision_id=new_revision.revision_id, type=r.type, objective_id=r.objective_id,
            skill_id=r.skill_id, resource_id=r.resource_id, practice_item_ids=r.practice_item_ids,
            est_minutes=r.est_minutes, difficulty=r.difficulty, day_slot=r.day_slot, depends_on=r.depends_on,
            reason=r.reason, status=r.status,
        )
        for r in restore_items
    ]
    if new_items:
        await planning_repo.create_items(new_items)
    plan_row.current_revision_id = new_revision.revision_id
    await planning_repo.mark_reverted(revision_id, reverted_by_revision_id=new_revision.revision_id)

    return WeeklyPlan(
        plan_id=plan_id, learner_id=learner_id, week_index=plan_row.week_index, hours_budget=plan_row.hours_budget,
        revision_no=new_revision.revision_no, status=plan_row.status, degraded=False,
        items=[_row_to_schema(r) for r in new_items], overall_reason=new_revision.overall_reason,
    )
