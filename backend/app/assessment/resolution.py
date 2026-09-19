"""Misconception resolution (design §20.8's "Resolution check and
termination", scoped down to a **deterministic** path -- the full
Reflection Agent (design §20's LLM-driven root-cause synthesis over a
closed operator set, `ReflectionResult`, the Plan Validator re-check loop)
is out of scope for this phase; see the Phase 8 brief's "RESOLUTION"
section, which asks only for: misconception detected -> remediation ->
verification probe -> resolved/persistent.

Both `INSERT_REMEDIATION` and `ADD_PROBE` (design §20.5's closed operator
set) are, by design, "deterministic function[s] on the plan" -- what a
Reflection Agent would decide *when* to fire is hard-coded here to exactly
one trigger (a `repeated_misconception` signal at `confirmed` status), and
this module applies both operators directly via `PlanningRepository`
rather than round-tripping through the Planner Agent/G2 graph, since
neither operator needs an LLM to execute once the trigger has already fired
deterministically.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.core.thresholds import MAX_REMEDIATION_CYCLES, STRUGGLE_REVISION_COOLDOWN_HOURS
from app.db.models import LearnerMisconception
from app.db.models import PlanItem as PlanItemRow
from app.db.models import PlanRevision as PlanRevisionRow
from app.graph.queries import SkillGraphService
from app.repositories.assessment_repository import AssessmentRepository, within_cooldown
from app.repositories.planning_repository import PlanningRepository

SUSPECTED = "suspected"
CONFIRMED = "confirmed"
REMEDIATING = "remediating"
RESOLVED = "resolved"
PERSISTENT = "persistent"


@dataclass
class RemediationOutcome:
    learner_misconception: LearnerMisconception
    remediation_resource_ids: list[str] = field(default_factory=list)
    started: bool = False  # False if skipped (cooldown, or already persistent)
    skip_reason: str | None = None
    plan_revision_id: str | None = None  # set if a plan revision was actually created


async def upsert_signal_status(
    repo: AssessmentRepository, *, learner_id: str, misconception_id: str, status: str, evidence_ids: list[str]
) -> LearnerMisconception:
    """Records/advances a `LearnerMisconception` row from a
    `repeated_misconception` struggle signal (`suspected` or `confirmed`).
    Never downgrades an already-`remediating`/`resolved`/`persistent` row
    back to `suspected` -- a fresh single-item occurrence after remediation
    has already started doesn't erase that history."""
    existing = await repo.get_learner_misconception(learner_id, misconception_id)
    if existing is None:
        return await repo.create_learner_misconception(
            LearnerMisconception(
                learner_id=learner_id, misconception_id=misconception_id, status=status, evidence_ids=evidence_ids
            )
        )
    if existing.status in (SUSPECTED, CONFIRMED):
        existing.status = status
        existing.evidence_ids = sorted(set(existing.evidence_ids) | set(evidence_ids))
    return existing


async def start_remediation(
    *,
    repo: AssessmentRepository,
    planning_repo: PlanningRepository,
    graph: SkillGraphService,
    learner_id: str,
    misconception_id: str,
    skill_id: str,
    probe_item_ids: list[str],
    evidence_ids: list[str],
) -> RemediationOutcome:
    """design §20.8: "After remediation, a resolution probe... is
    scheduled." Deterministic remediation-resource selection
    (`SkillGraphService.remediation_resources_for_misconception`, design
    §11.3's `REMEDIATED_BY` edges -- never an LLM pick) plus a direct,
    deterministic `PlanRevision`/`PlanItem` insertion when the learner has
    an active plan. A misconception already `persistent` is never
    re-remediated (design §20.8: "does not loop indefinitely"); one already
    `remediating` within the cooldown window is skipped, not restarted
    (design §19.4's anti-thrashing cooldown, applied here to remediation
    triggers specifically).
    """
    lm = await repo.get_learner_misconception(learner_id, misconception_id)
    if lm is None:
        lm = await repo.create_learner_misconception(
            LearnerMisconception(learner_id=learner_id, misconception_id=misconception_id, status=CONFIRMED, evidence_ids=evidence_ids)
        )

    if lm.status == PERSISTENT:
        return RemediationOutcome(learner_misconception=lm, started=False, skip_reason="persistent -- escalated, not re-remediated")
    if lm.status == REMEDIATING and within_cooldown(lm.last_remediated_at, cooldown_hours=STRUGGLE_REVISION_COOLDOWN_HOURS):
        return RemediationOutcome(learner_misconception=lm, started=False, skip_reason="cooldown active")

    try:
        remediation_resource_ids = graph.remediation_resources_for_misconception(misconception_id)
    except ValueError:
        remediation_resource_ids = []  # unknown misconception_id -- nothing to attach, still schedule the probe

    lm.status = REMEDIATING
    lm.last_remediated_at = datetime.now(timezone.utc)
    lm.evidence_ids = sorted(set(lm.evidence_ids) | set(evidence_ids))

    plan_revision_id = await _apply_remediation_to_plan(
        planning_repo=planning_repo,
        learner_id=learner_id,
        skill_id=skill_id,
        resource_ids=remediation_resource_ids,
        probe_item_ids=probe_item_ids,
        misconception_id=misconception_id,
    )

    return RemediationOutcome(
        learner_misconception=lm, remediation_resource_ids=remediation_resource_ids, started=True, plan_revision_id=plan_revision_id
    )


async def record_probe_result(
    repo: AssessmentRepository, *, learner_id: str, misconception_id: str, passed: bool
) -> LearnerMisconception:
    """design §20.8: "Pass -> misconception resolved... Fail -> a second
    remediation cycle... After two failed remediation cycles -> persistent."
    """
    lm = await repo.get_learner_misconception(learner_id, misconception_id)
    if lm is None:
        raise ValueError(f"no LearnerMisconception row for ({learner_id!r}, {misconception_id!r}) to resolve")

    if passed:
        lm.status = RESOLVED
        lm.resolved_at = datetime.now(timezone.utc)
        return lm

    lm.remediation_cycles += 1
    lm.status = PERSISTENT if lm.remediation_cycles >= MAX_REMEDIATION_CYCLES else REMEDIATING
    return lm


async def _apply_remediation_to_plan(
    *,
    planning_repo: PlanningRepository,
    learner_id: str,
    skill_id: str,
    resource_ids: list[str],
    probe_item_ids: list[str],
    misconception_id: str,
) -> str | None:
    """`INSERT_REMEDIATION` + `ADD_PROBE` (design §20.5), applied directly:
    a new `PlanRevision` carrying forward every item from the current
    revision (design §20.7: "revisions apply to future items only" --
    already-`done` items are carried over unchanged, not deleted) plus a
    `review` item for the remediation resource (if any) and a `probe` item
    for the resolution-check set. Returns `None` (no-op) if the learner has
    no active plan yet -- there is nothing to remediate."""
    plan_row = await planning_repo.get_current_plan_for_learner(learner_id)
    if plan_row is None or plan_row.current_revision_id is None:
        return None

    prior_items = await planning_repo.list_items_for_revision(plan_row.current_revision_id)
    prior_revisions = await planning_repo.list_revisions(plan_row.plan_id)
    revision_no = len(prior_revisions) + 1
    max_day_slot = max((i.day_slot for i in prior_items), default=1)

    revision = await planning_repo.create_revision(
        PlanRevisionRow(
            plan_id=plan_row.plan_id,
            revision_no=revision_no,
            parent_revision_id=plan_row.current_revision_id,
            cause_type="remediation",
            cause_ref=f"misconception:{misconception_id}",
            operators=[
                {"op": "INSERT_REMEDIATION", "params": {"skill_id": skill_id, "resource_ids": resource_ids}},
                {"op": "ADD_PROBE", "params": {"skill_id": skill_id, "purpose": "resolution-check"}},
            ],
            diff={},
            degraded=False,
            overall_reason=f"Remediation for a confirmed misconception on {skill_id}, with a follow-up verification probe.",
        )
    )

    new_items = [
        PlanItemRow(
            plan_id=plan_row.plan_id,
            revision_id=revision.revision_id,
            type=i.type,
            objective_id=i.objective_id,
            skill_id=i.skill_id,
            resource_id=i.resource_id,
            practice_item_ids=i.practice_item_ids,
            est_minutes=i.est_minutes,
            difficulty=i.difficulty,
            day_slot=i.day_slot,
            depends_on=i.depends_on,
            reason=i.reason,
            status=i.status,
        )
        for i in prior_items
    ]
    for resource_id in resource_ids[:1]:  # one remediation resource is enough for one revision
        new_items.append(
            PlanItemRow(
                plan_id=plan_row.plan_id,
                revision_id=revision.revision_id,
                type="review",
                objective_id=f"remediation.{misconception_id}",
                skill_id=skill_id,
                resource_id=resource_id,
                practice_item_ids=[],
                est_minutes=20,
                difficulty=1,
                day_slot=max_day_slot,
                depends_on=[],
                reason={"text": f"Remediation for a confirmed misconception on {skill_id}.", "evidence_ids": [], "graph_path": None, "decision_id": None},
                status="planned",
            )
        )
    if probe_item_ids:
        new_items.append(
            PlanItemRow(
                plan_id=plan_row.plan_id,
                revision_id=revision.revision_id,
                type="probe",
                objective_id=f"remediation.{misconception_id}",
                skill_id=skill_id,
                resource_id=None,
                practice_item_ids=probe_item_ids,
                est_minutes=len(probe_item_ids) * 3,
                difficulty=1,
                day_slot=min(max_day_slot + 1, 5),
                depends_on=[],
                reason={"text": "Verification probe: confirms whether the remediation resolved the misconception.", "evidence_ids": [], "graph_path": None, "decision_id": None},
                status="planned",
            )
        )

    await planning_repo.create_items(new_items)
    plan_row.current_revision_id = revision.revision_id
    return revision.revision_id
