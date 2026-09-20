"""Report Builder (design §25.2's `ProgressReport`; the Phase 10 brief's
explicit requirement: "Report Builder must deterministically calculate
acquired/in-progress/remaining/struggle/next-steps... it must NOT calculate
the statistics itself [in the LLM]").

`build_progress_report` is a **pure function** over already-fetched, plain
data (the Gap Engine's own `GapAnalysisResult`, small framework-independent
record types for skill-state/struggle/misconception rows, and the Planner's
`PlanItem` schema) -- no DB/gateway import in this half of the module, the
same "pure algorithm, unit-testable with hand-built fixtures" split
`app/gap/engine.py`/`app/assessment/struggle.py`/`app/planning/validator.py`
already established. `compute_progress_report` is the async orchestration
half (mirrors `app/retrieval/service.py`'s split): it fetches the real rows
and calls straight into the pure function -- it never re-derives a number
the pure function already owns.

Bucketing is a direct partition of the Gap Engine's own already-computed
`SkillGapEntry.status` (never a second, independently-invented notion of
"acquired"/"in progress"): `MET` -> acquired, `WEAK` -> in progress (some
real evidence, not yet enough), everything else (`MISSING`, `BLOCKED`,
`UNVERIFIED`) -> remaining gaps. `acquired` reuses the Gap Engine's own
`strengths[]` output (design §13.1) rather than re-deriving mastery/evidence
from raw `SkillGapEntry` fields it doesn't carry.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.core.thresholds import PROGRESS_REPORT_NEXT_STEPS_LIMIT
from app.gap.engine import BLOCKED, MET, MISSING, UNVERIFIED, WEAK, GapAnalysisResult
from app.schemas.common import PlanItem
from app.tutor.context import TutorContext

# ---------------------------------------------------------------------------
# Inputs (framework-independent — see module docstring)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SkillStateRecord:
    """The subset of `LearnerSkillState` (app/db/models.py) the Report
    Builder needs for the `in_progress` bucket's `band` display field."""

    skill_id: str
    band: str  # unknown | learning | developing | proficient


@dataclass(frozen=True)
class StruggleSignalRecord:
    signal_id: str
    skill_id: str
    signal_class: str
    confidence: str
    status: str  # open | closed


@dataclass(frozen=True)
class MisconceptionStatusRecord:
    misconception_id: str
    skill_id: str
    status: str  # suspected | confirmed | remediating | resolved | persistent


# ---------------------------------------------------------------------------
# Outputs (design §25.2)
# ---------------------------------------------------------------------------


@dataclass
class ProgressSkillEntry:
    skill_id: str
    label: str
    status: str
    mastery: float = 0.0
    band: str = "unknown"
    tier_max: str = ""
    evidence_ids: list[str] = field(default_factory=list)


@dataclass
class StruggleAreaEntry:
    skill_id: str
    status: str
    signal_id: str | None = None
    signal_class: str | None = None
    confidence: str | None = None
    misconception_id: str | None = None


@dataclass
class ProgressActivityEntry:
    item_id: str
    skill_id: str
    type: str
    est_minutes: int
    day_slot: int
    status: str


@dataclass
class ProgressReportData:
    learner_id: str
    role_id: str
    period: str
    graph_version: str
    acquired: list[ProgressSkillEntry] = field(default_factory=list)
    in_progress: list[ProgressSkillEntry] = field(default_factory=list)
    remaining_gaps: list = field(default_factory=list)  # list[SkillGapEntry], re-exported as-is
    struggle_areas: list[StruggleAreaEntry] = field(default_factory=list)
    completed_work: list[ProgressActivityEntry] = field(default_factory=list)
    next_steps: list[ProgressActivityEntry] = field(default_factory=list)


def build_progress_report(
    *,
    learner_id: str,
    period: str,
    gap_result: GapAnalysisResult,
    skill_states: dict[str, SkillStateRecord],
    struggle_signals: list[StruggleSignalRecord],
    misconceptions: list[MisconceptionStatusRecord],
    plan_items: list[PlanItem],
) -> ProgressReportData:
    acquired = [
        ProgressSkillEntry(
            skill_id=s.skill_id, label=s.label, status=MET, mastery=s.mastery,
            band=skill_states.get(s.skill_id, SkillStateRecord(s.skill_id, "unknown")).band,
            tier_max=s.tier_max, evidence_ids=list(s.evidence_ids),
        )
        for s in gap_result.strengths
    ]

    in_progress = [
        ProgressSkillEntry(
            skill_id=g.skill_id, label=g.label, status=g.status,
            band=skill_states.get(g.skill_id, SkillStateRecord(g.skill_id, "unknown")).band,
            evidence_ids=list(g.evidence_ids),
        )
        for g in gap_result.gaps
        if g.status == WEAK
    ]

    remaining_gaps = [g for g in gap_result.gaps if g.status in (MISSING, BLOCKED, UNVERIFIED)]

    struggle_areas = [
        StruggleAreaEntry(
            skill_id=sig.skill_id, status=sig.status, signal_id=sig.signal_id,
            signal_class=sig.signal_class, confidence=sig.confidence,
        )
        for sig in struggle_signals
        if sig.status == "open"
    ] + [
        StruggleAreaEntry(skill_id=m.skill_id, status=m.status, misconception_id=m.misconception_id)
        for m in misconceptions
        if m.status in ("suspected", "confirmed", "remediating")
    ]

    completed_work = [
        ProgressActivityEntry(
            item_id=i.item_id, skill_id=i.skill_id, type=i.type, est_minutes=i.est_minutes,
            day_slot=i.day_slot, status=i.status,
        )
        for i in plan_items
        if i.status == "done"
    ]
    next_steps = sorted(
        (
            ProgressActivityEntry(
                item_id=i.item_id, skill_id=i.skill_id, type=i.type, est_minutes=i.est_minutes,
                day_slot=i.day_slot, status=i.status,
            )
            for i in plan_items
            if i.status == "planned"
        ),
        key=lambda a: a.day_slot,
    )[:PROGRESS_REPORT_NEXT_STEPS_LIMIT]

    return ProgressReportData(
        learner_id=learner_id, role_id=gap_result.role_id, period=period, graph_version=gap_result.graph_version,
        acquired=acquired, in_progress=in_progress, remaining_gaps=remaining_gaps,
        struggle_areas=struggle_areas, completed_work=completed_work, next_steps=next_steps,
    )


async def compute_progress_report(ctx: TutorContext, *, period: str = "all_time") -> ProgressReportData:
    """Async orchestration half: fetch the real rows, map them to the pure
    function's plain record types, and call straight through -- never
    re-derives a bucket/number itself (see module docstring)."""
    skill_state_rows = await ctx.profiling_repo.list_skill_states_for_learner(ctx.learner_id)
    skill_states = {s.skill_id: SkillStateRecord(skill_id=s.skill_id, band=s.band) for s in skill_state_rows}

    signal_rows = await ctx.assessment_repo.list_signals_for_learner(ctx.learner_id)
    struggle_signals = [
        StruggleSignalRecord(
            signal_id=s.signal_id, skill_id=s.skill_id, signal_class=s.signal_class,
            confidence=s.confidence, status=s.status,
        )
        for s in signal_rows
    ]

    misconception_rows = await ctx.assessment_repo.list_open_misconceptions(ctx.learner_id)
    # `LearnerMisconception` carries only the misconception id; the skill it
    # affects lives on the curated `Misconception` row (design §28).
    misconceptions: list[MisconceptionStatusRecord] = []
    for m in misconception_rows:
        catalog_row = await ctx.catalog.get_misconception(m.misconception_id)
        if catalog_row is None:
            continue  # a misconception removed from the catalog since it was detected: nothing to attribute it to
        misconceptions.append(
            MisconceptionStatusRecord(misconception_id=m.misconception_id, skill_id=catalog_row.skill_id, status=m.status)
        )

    plan_items: list[PlanItem] = []
    plan_row = await ctx.planning_repo.get_current_plan_for_learner(ctx.learner_id)
    if plan_row is not None and plan_row.current_revision_id is not None:
        item_rows = await ctx.planning_repo.list_items_for_revision(plan_row.current_revision_id)
        plan_items = [
            PlanItem(
                item_id=r.item_id, type=r.type, objective_id=r.objective_id, skill_id=r.skill_id,
                resource_id=r.resource_id, practice_item_ids=r.practice_item_ids, est_minutes=r.est_minutes,
                difficulty=r.difficulty, day_slot=r.day_slot, depends_on=r.depends_on, status=r.status,
            )
            for r in item_rows
        ]

    return build_progress_report(
        learner_id=ctx.learner_id, period=period, gap_result=ctx.gap_result, skill_states=skill_states,
        struggle_signals=struggle_signals, misconceptions=misconceptions, plan_items=plan_items,
    )
