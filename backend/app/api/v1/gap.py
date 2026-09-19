"""Skill-Gap Engine endpoint (design §27: `GET /api/learners/me/gaps`).

Deterministic only (ARCHITECTURE_CONTRACTS.md §4) — this route reads
`LearnerSkillState`/`Evidence` (Phase 2) and the curated Skill Graph (Phase
3), converts them into the Gap Engine's plain-data inputs, and returns its
output. No LangGraph run, no LLM call, no orchestrator column in design §27's
table for this endpoint — a bare deterministic service call, same as
`role_subgraph`/`explain_skill_path` already are.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_learner_id, get_skill_graph_service
from app.db.session import get_session
from app.gap.engine import EvidenceRecord, LearnerSkillRecord, analyze_gaps
from app.graph.queries import SkillGraphService, UnknownRoleError
from app.repositories.profiling_repository import ProfilingRepository
from app.schemas.common import LearningObjective as LearningObjectiveOut
from app.schemas.common import SkillGap as SkillGapOut
from app.schemas.gap import AuditFlag as AuditFlagOut
from app.schemas.gap import GapGraphEdge, GapReport
from app.schemas.gap import Strength as StrengthOut

router = APIRouter(prefix="/learners", tags=["gaps"])


@router.get("/me/gaps", response_model=GapReport)
async def get_gaps(
    role: str | None = None,
    learner_id: str = Depends(get_current_learner_id),
    session: AsyncSession = Depends(get_session),
    graph_service: SkillGraphService = Depends(get_skill_graph_service),
) -> GapReport:
    repo = ProfilingRepository(session)

    role_id = role
    if role_id is None:
        profile = await repo.get_learner_profile(learner_id)
        # get_current_learner_id already guarantees a profile exists for this
        # learner_id (it is the profile's own primary key), so this is just
        # the type checker's None -- not a real "no profile" branch.
        role_id = profile.target_role_id if profile is not None else None
    if role_id is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="role not supported")

    skill_states = await repo.list_skill_states_for_learner(learner_id)
    evidence_rows = await repo.list_evidence_for_learner(learner_id)

    skill_records = [
        LearnerSkillRecord(skill_id=s.skill_id, alpha=s.alpha, beta=s.beta, tier_max=s.tier_max, n_obs=s.n_obs)
        for s in skill_states
    ]
    evidence_records = [
        EvidenceRecord(evidence_id=e.evidence_id, skill_id=e.skill_id, tier=e.tier) for e in evidence_rows
    ]

    try:
        result = analyze_gaps(role_id, skill_records, evidence_records, graph_service)
    except UnknownRoleError as exc:
        # ARCHITECTURE_CONTRACTS.md §5: "If a requested role is not in the
        # curated graph: return 'role not supported'. Never invent a graph
        # at runtime."
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="role not supported") from exc

    return GapReport(
        role_id=result.role_id,
        graph_version=result.graph_version,
        gaps=[
            SkillGapOut(
                skill_id=g.skill_id,
                label=g.label,
                status=g.status,
                gap_type=g.gap_type,
                required_level=g.required_level,
                current_level=g.current_level,
                blocked_by=g.blocked_by,
                root_of=g.root_of,
                priority=g.priority,
                ordering_layer=g.ordering_layer,
                evidence_ids=g.evidence_ids,
                audit_flags=g.audit_flags,
            )
            for g in result.gaps
        ],
        strengths=[
            StrengthOut(
                skill_id=s.skill_id,
                label=s.label,
                required_level=s.required_level,
                current_level=s.current_level,
                tier_max=s.tier_max,
                mastery=s.mastery,
                evidence_ids=s.evidence_ids,
            )
            for s in result.strengths
        ],
        audit_flags=[
            AuditFlagOut(
                flag_type=f.flag_type, skill_id=f.skill_id, message=f.message, related_skill_ids=f.related_skill_ids
            )
            for f in result.audit_flags
        ],
        objectives=[
            LearningObjectiveOut(
                objective_id=o.objective_id,
                skill_id=o.skill_id,
                from_status=o.from_status,
                objective_type=o.objective_type,
                target_level=o.target_level,
                priority=o.priority,
                prerequisite_objective_ids=o.prerequisite_objective_ids,
                acceptance_criteria=o.acceptance_criteria,
                est_minutes_low=o.est_minutes_low,
                est_minutes_high=o.est_minutes_high,
                reason_ref=o.reason_ref,
            )
            for o in result.objectives
        ],
        layers=result.layers,
        prerequisite_edges=[GapGraphEdge(from_skill_id=p, to_skill_id=s) for p, s in result.prerequisite_edges],
    )
