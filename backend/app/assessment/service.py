"""Async orchestration for the Practice & Assessment Engine -- design §9.5's
G3 Evidence-Response, scoped to this phase: `record_evidence -> grade ->
update_mastery -> detect_struggle -> route (-> deterministic remediation)`.
The full `reflect` node (Reflection Agent, LLM-driven root-cause synthesis)
is out of scope; `route` here only ever triggers the deterministic
remediation path in `app/assessment/resolution.py` for a *confirmed*
`repeated_misconception` signal specifically (see that module's docstring).

Mirrors `app/profiling/onboarding.py`/`app/planning/service.py`'s split
between "pure algorithm" (`mastery.py`, `struggle.py`) and "DB/gateway
glue" (this module).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.assessor import AssessorAgent
from app.assessment import resolution
from app.assessment.grading import grade_mcq
from app.assessment.item_bank import assemble_practice_set
from app.assessment.mastery import compute_band, compute_confidence, update_mastery
from app.assessment.struggle import (
    REPEATED_MISCONCEPTION,
    ItemOutcome,
    StruggleContext,
    StruggleSignalEntry,
    classify_struggle,
)
from app.core.thresholds import REPEATED_MISCONCEPTION_WINDOW_DAYS
from app.db.models import Assessment, Evidence, LearnerSkillState, PracticeSession
from app.db.models import StruggleSignal as StruggleSignalRow
from app.gap.engine import EvidenceRecord, LearnerSkillRecord, analyze_gaps, current_level_for
from app.gateway.llm_gateway import LLMGateway
from app.graph.queries import SkillGraphService
from app.repositories.assessment_repository import AssessmentRepository
from app.repositories.catalog_repository import CatalogRepository
from app.repositories.planning_repository import PlanningRepository
from app.repositories.profiling_repository import ProfilingRepository


class UnknownPracticeSessionError(Exception):
    pass


@dataclass
class SubmittedAnswer:
    item_id: str
    chosen_option: int
    time_sec: int | None = None


@dataclass
class SubmitOutcome:
    assessment_id: str
    skill_id: str
    purpose: str
    score: float
    items: list[dict] = field(default_factory=list)  # design §25.2's AssessmentResult.items[] shape, as dicts
    signals: list[StruggleSignalEntry] = field(default_factory=list)
    remediation: resolution.RemediationOutcome | None = None
    submitted_at: str = ""


async def create_practice_session(
    *,
    session: AsyncSession,
    graph: SkillGraphService,
    llm_gateway: LLMGateway,
    learner_id: str,
    skill_id: str,
    purpose: str = "practice",
    misconception_id: str | None = None,
) -> PracticeSession:
    """design §27's `POST /api/learners/me/practice`. Never returns
    misconception tags or keys to the caller -- the response shape built
    from this (`app/api/v1/practice.py`) only ever exposes `set_id`/
    `item_id`/`stem`/`options[].text` (design §18.3)."""
    catalog = CatalogRepository(session)
    profiling_repo = ProfilingRepository(session)
    assessment_repo = AssessmentRepository(session)
    assessor_agent = AssessorAgent(llm_gateway)

    profile = await profiling_repo.get_learner_profile(learner_id)
    gap_statuses: dict[str, str] = {}
    if profile is not None:
        skill_records, evidence_records = await _build_records(profiling_repo, learner_id)
        try:
            gap_result = analyze_gaps(profile.target_role_id, skill_records, evidence_records, graph)
            gap_statuses = {g.skill_id: g.status for g in gap_result.gaps}
        except Exception:  # noqa: BLE001 -- role not supported / skill outside scope: no prereq-block context, not fatal
            gap_statuses = {}

    state = await profiling_repo.get_learner_skill_state(learner_id, skill_id)
    current_level = current_level_for(
        LearnerSkillRecord(skill_id=skill_id, alpha=state.alpha, beta=state.beta, tier_max=state.tier_max, n_obs=state.n_obs)
        if state is not None
        else None
    )

    prior_assessments = await assessment_repo.list_assessments_for_skill(learner_id, skill_id)
    seen_item_ids = {entry["item_id"] for a in prior_assessments for entry in a.items}

    assembled = await assemble_practice_set(
        catalog=catalog,
        graph=graph,
        assessor_agent=assessor_agent,
        skill_id=skill_id,
        current_level=current_level,
        purpose=purpose,
        gap_statuses=gap_statuses,
        seen_item_ids=seen_item_ids,
        misconception_id=misconception_id,
    )

    return await assessment_repo.create_practice_session(
        PracticeSession(
            learner_id=learner_id,
            skill_id=skill_id,
            purpose=purpose,
            item_ids=assembled.item_ids,
            misconception_id=misconception_id,
        )
    )


async def submit_practice_set(
    *,
    session: AsyncSession,
    graph: SkillGraphService,
    llm_gateway: LLMGateway,
    learner_id: str,
    set_id: str,
    answers: list[SubmittedAnswer],
    self_reported_overload: bool = False,
    planned_vs_actual_ratio: float | None = None,
    completion_rate: float | None = None,
    retries_trend_rising: bool = False,
    new_skills_active: int = 0,
    new_skill_concurrency_cap: int = 3,
) -> SubmitOutcome:
    """design §27's `POST /api/practice/{set_id}/submit`, and design §9.5's
    `record_evidence -> grade -> update_mastery -> detect_struggle -> route`
    end to end. `self_reported_overload`/`planned_vs_actual_ratio`/etc. are
    optional caller-supplied overload signals (design §19.1's "self-reported
    too heavy/too easy (optional)") -- no `LearningActivity` table exists
    yet to source `planned_vs_actual_ratio`/`completion_rate` from live data
    (Phase 5/6's "mechanism now, real source later" pattern), so a caller
    without them simply gets fewer corroborating signals to work with, never
    a crash.
    """
    catalog = CatalogRepository(session)
    profiling_repo = ProfilingRepository(session)
    assessment_repo = AssessmentRepository(session)
    planning_repo = PlanningRepository(session)

    practice_session = await assessment_repo.get_practice_session(learner_id, set_id)
    if practice_session is None:
        raise UnknownPracticeSessionError(f"unknown practice set_id {set_id!r} for this learner")

    items_by_id = {it.item_id: it for it in await catalog.get_practice_items_by_ids(practice_session.item_ids)}
    answers_by_item = {a.item_id: a for a in answers if a.item_id in items_by_id}

    item_results: list[dict] = []
    outcomes: list[ItemOutcome] = []
    for item_id, item in items_by_id.items():
        answer = answers_by_item.get(item_id)
        if answer is None:
            continue  # unanswered item -- not graded, not counted
        grade = grade_mcq(item, answer.chosen_option)
        item_results.append(
            {
                "item_id": item_id,
                "skill_id": item.skill_id,
                "difficulty": item.difficulty,
                "chosen_option": answer.chosen_option,
                "correct": grade.correct,
                "misconception_id": grade.misconception_id,
                "time_sec": answer.time_sec,
                "attempt_no": 1,
            }
        )
        outcomes.append(
            ItemOutcome(
                item_id=item_id,
                skill_id=item.skill_id,
                difficulty=item.difficulty,
                correct=grade.correct,
                misconception_id=grade.misconception_id,
                time_sec=answer.time_sec,
            )
        )

    target_items = [r for r in item_results if r["skill_id"] == practice_session.skill_id]
    score = (sum(1 for r in target_items if r["correct"]) / len(target_items)) if target_items else 0.0
    prereq_items = [r for r in item_results if r["skill_id"] != practice_session.skill_id]
    prereq_block_score = (
        (sum(1 for r in prereq_items if r["correct"]) / len(prereq_items)) if prereq_items else None
    )

    assessment = await assessment_repo.create_assessment(
        Assessment(
            learner_id=learner_id,
            purpose=practice_session.purpose,
            skill_id=practice_session.skill_id,
            items=item_results,
            score=score,
            prereq_block_score=prereq_block_score,
            submitted_at=datetime.now(timezone.utc),  # explicit, not server_default -- read back in this same request
        )
    )
    practice_session.status = "submitted"

    # -- resolution-check sets: record the probe outcome, never re-run the full struggle pipeline over it --
    if practice_session.purpose == "resolution-check" and practice_session.misconception_id:
        passed = score >= 1.0 if target_items else False
        await resolution.record_probe_result(
            assessment_repo, learner_id=learner_id, misconception_id=practice_session.misconception_id, passed=passed
        )
        return SubmitOutcome(
            assessment_id=assessment.assessment_id, skill_id=practice_session.skill_id, purpose=practice_session.purpose,
            score=score, items=item_results, submitted_at=assessment.submitted_at.isoformat() if assessment.submitted_at else "",
        )

    # -- record_evidence + update_mastery (design §9.5) --
    mastery_by_skill = {}
    for skill_id in {r["skill_id"] for r in item_results}:
        skill_items = [r for r in item_results if r["skill_id"] == skill_id]
        state = await profiling_repo.get_learner_skill_state(learner_id, skill_id)
        existing_record = (
            LearnerSkillRecord(skill_id=skill_id, alpha=state.alpha, beta=state.beta, tier_max=state.tier_max, n_obs=state.n_obs)
            if state is not None
            else None
        )
        for r in skill_items:
            outcome = update_mastery(existing_record, skill_id=skill_id, correct=r["correct"], difficulty=r["difficulty"])
            existing_record = LearnerSkillRecord(skill_id=skill_id, alpha=outcome.alpha, beta=outcome.beta, tier_max=outcome.tier_max, n_obs=outcome.n_obs)
        mastery_by_skill[skill_id] = existing_record
        _upsert_skill_state(profiling_repo, state, learner_id, skill_id, existing_record)

        await profiling_repo.create_evidence(
            Evidence(
                learner_id=learner_id,
                skill_id=skill_id,
                tier="E3",
                source_type="assessment",
                span_text=f"assessment {assessment.assessment_id}: {sum(1 for r in skill_items if r['correct'])}/{len(skill_items)} correct",
                span_offsets=None,
                assessment_id=assessment.assessment_id,
                verified=True,
            )
        )

    # -- detect_struggle (design §9.5/§19.2) --
    target_record = mastery_by_skill.get(practice_session.skill_id)
    hard_prereqs = graph.direct_prerequisites(practice_session.skill_id, include_soft=False)
    gap_statuses: dict[str, str] = {}
    profile = await profiling_repo.get_learner_profile(learner_id)
    if profile is not None:
        skill_records, evidence_records = await _build_records(profiling_repo, learner_id)
        try:
            gap_result = analyze_gaps(profile.target_role_id, skill_records, evidence_records, graph)
            gap_statuses = {g.skill_id: g.status for g in gap_result.gaps}
        except Exception:  # noqa: BLE001 -- role not supported / out of scope, not fatal
            gap_statuses = {}
    hard_prerequisite_status = {p: gap_statuses[p] for p in hard_prereqs if p in gap_statuses}

    misconception_root_skill: dict[str, str] = {}
    for r in item_results:
        mid = r["misconception_id"]
        if mid and mid not in misconception_root_skill:
            m = await catalog.get_misconception(mid)
            if m is not None:
                misconception_root_skill[mid] = m.root_skill_id

    since = datetime.now(timezone.utc) - timedelta(days=REPEATED_MISCONCEPTION_WINDOW_DAYS)
    prior_misconception_item_counts: dict[str, int] = {}
    for mid in {r["misconception_id"] for r in item_results if r["misconception_id"]}:
        prior_misconception_item_counts[mid] = await assessment_repo.count_prior_misconception_items(learner_id, mid, since=since)
        # `since` already covers this just-persisted assessment, so subtract this attempt's own contribution.
        this_attempt = len({r["item_id"] for r in item_results if r["misconception_id"] == mid})
        prior_misconception_item_counts[mid] = max(0, prior_misconception_item_counts[mid] - this_attempt)

    context = StruggleContext(
        skill_id=practice_session.skill_id,
        current_level=current_level_for(target_record) if target_record else 0,
        mastery_estimate=target_record.alpha / (target_record.alpha + target_record.beta) if target_record else 0.0,
        n_obs=target_record.n_obs if target_record else 0,
        hard_prerequisite_status=hard_prerequisite_status,
        prerequisite_probe_scores={},
        misconception_root_skill=misconception_root_skill,
        prior_misconception_item_counts=prior_misconception_item_counts,
        planned_vs_actual_ratio=planned_vs_actual_ratio,
        completion_rate=completion_rate,
        self_reported_overload=self_reported_overload,
        retries_trend_rising=retries_trend_rising,
        new_skills_active=new_skills_active,
        new_skill_concurrency_cap=new_skill_concurrency_cap,
    )
    signals = classify_struggle(outcomes, context)

    for s in signals:
        row = await assessment_repo.create_signal(
            StruggleSignalRow(
                learner_id=learner_id, signal_class=s.signal_class, skill_id=s.skill_id, confidence=s.confidence,
                evidence_ids=s.evidence_ids, counts=s.counts, thresholds_used=s.thresholds_used,
            )
        )
        s.signal_id = row.signal_id

    # -- route: deterministic remediation for a confirmed repeated misconception (design §19.3/§20.8) --
    remediation_outcome: resolution.RemediationOutcome | None = None
    for s in signals:
        if s.signal_class == REPEATED_MISCONCEPTION and s.confidence == "high" and s.counts.get("status") == "confirmed":
            misconception_id = s.counts["misconception_id"]
            lm = await resolution.upsert_signal_status(
                assessment_repo, learner_id=learner_id, misconception_id=misconception_id, status="confirmed", evidence_ids=s.evidence_ids
            )
            probe_session = await create_practice_session(
                session=session, graph=graph, llm_gateway=llm_gateway, learner_id=learner_id, skill_id=practice_session.skill_id,
                purpose="resolution-check", misconception_id=misconception_id,
            )
            remediation_outcome = await resolution.start_remediation(
                repo=assessment_repo, planning_repo=planning_repo, graph=graph, learner_id=learner_id,
                misconception_id=misconception_id, skill_id=practice_session.skill_id, probe_item_ids=probe_session.item_ids,
                evidence_ids=s.evidence_ids,
            )
            break  # design §19.4: only one triggered revision per submission

    return SubmitOutcome(
        assessment_id=assessment.assessment_id,
        skill_id=practice_session.skill_id,
        purpose=practice_session.purpose,
        score=score,
        items=item_results,
        signals=signals,
        remediation=remediation_outcome,
        submitted_at=assessment.submitted_at.isoformat() if assessment.submitted_at else "",
    )


async def _build_records(
    profiling_repo: ProfilingRepository, learner_id: str
) -> tuple[list[LearnerSkillRecord], list[EvidenceRecord]]:
    skill_states = await profiling_repo.list_skill_states_for_learner(learner_id)
    evidence_rows = await profiling_repo.list_evidence_for_learner(learner_id)
    skill_records = [
        LearnerSkillRecord(skill_id=s.skill_id, alpha=s.alpha, beta=s.beta, tier_max=s.tier_max, n_obs=s.n_obs)
        for s in skill_states
    ]
    evidence_records = [
        EvidenceRecord(evidence_id=e.evidence_id, skill_id=e.skill_id, tier=e.tier) for e in evidence_rows
    ]
    return skill_records, evidence_records


def _upsert_skill_state(
    profiling_repo: ProfilingRepository,
    existing: LearnerSkillState | None,
    learner_id: str,
    skill_id: str,
    record: LearnerSkillRecord,
) -> None:
    """Unlike `EvidenceCommitService._upsert_skill_state` (Phase 2), which
    reseeds alpha/beta to a flat prior on a tier upgrade, the Mastery
    Updater always writes the accumulated alpha/beta `update_mastery`
    (`app/assessment/mastery.py`) just computed -- see that module's
    `ASSESSED_TIER` note for why these two update rules deliberately
    differ."""
    estimate = record.alpha / (record.alpha + record.beta) if (record.alpha + record.beta) > 0 else 0.0
    band = compute_band(estimate, record.n_obs, record.tier_max)
    confidence = compute_confidence(record.n_obs)

    if existing is None:
        profiling_repo.session.add(
            LearnerSkillState(
                learner_id=learner_id, skill_id=skill_id, alpha=record.alpha, beta=record.beta, band=band,
                confidence=confidence, n_obs=record.n_obs, tier_max=record.tier_max, last_assessed_at=datetime.now(timezone.utc),
            )
        )
        return
    existing.alpha = record.alpha
    existing.beta = record.beta
    existing.band = band
    existing.confidence = confidence
    existing.n_obs = record.n_obs
    existing.tier_max = record.tier_max
    existing.last_assessed_at = datetime.now(timezone.utc)
