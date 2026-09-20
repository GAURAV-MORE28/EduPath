"""Read-only view endpoints for the frontend (Phase 11).

Nothing here decides anything: roles, skill labels, resource metadata,
evidence spans, revision history and per-skill detail are projections of rows
earlier phases already own. The one write is marking a plan item
planned/done/skipped (ARCHITECTURE_CONTRACTS.md §20). `learner_id` is always
session-derived (§7); catalog lookups are global.
"""
from __future__ import annotations

import posixpath
import re

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_learner_id, get_skill_graph_service
from app.db.models import Document, PlanRevision, RoleRequirement, Skill
from app.db.models import PlanItem as PlanItemRow
from app.db.session import get_session
from app.gap.engine import EvidenceRecord, LearnerSkillRecord, analyze_gaps
from app.graph.queries import SkillGraphService, UnknownRoleError
from app.repositories.assessment_repository import AssessmentRepository
from app.repositories.catalog_repository import CatalogRepository
from app.repositories.planning_repository import PlanningRepository
from app.repositories.profiling_repository import ProfilingRepository
from app.repositories.reflection_repository import ReflectionRepository
from app.schemas.common import PlanItem, PlanItemReason, SkillGap
from app.schemas.profiling import LearnerProfileOut
from app.schemas.views import (
    EvidenceOut,
    MasteryOut,
    MisconceptionOut,
    PlanRevisionDetailOut,
    PlanRevisionOut,
    PrerequisiteOut,
    ResourceOut,
    RoleOut,
    RoleRequirementOut,
    SkillDetailOut,
    SkillOut,
    SkillPlanItemOut,
    UpdatePlanItemRequest,
)

router = APIRouter(tags=["views"])

_MAX_IDS = 200


def _split_ids(ids: str | None) -> list[str]:
    if not ids:
        return []
    parts = [p.strip() for p in ids.split(",") if p.strip()]
    if len(parts) > _MAX_IDS:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=f"at most {_MAX_IDS} ids")
    return parts


def _skill_out(s: Skill) -> SkillOut:
    return SkillOut(skill_id=s.skill_id, label=s.label, kind=s.kind, area=s.area, description=s.description or "")


def _resource_out(r) -> ResourceOut:
    return ResourceOut(
        resource_id=r.resource_id, title=r.title, url=r.url, provider=r.provider, type=r.type,
        difficulty=r.difficulty, duration_min=r.duration_min, modality=r.modality,
        learning_objective_text=r.learning_objective_text or "", cost=r.cost or "",
        link_status=r.link_status or "", curation_tier=r.curation_tier or "",
    )


def _document_label(doc: Document | None) -> str | None:
    """A file name or repo URL only -- never the server-side storage path."""
    if doc is None:
        return None
    ref = doc.storage_ref or ""
    if doc.type == "github":
        return ref
    name = posixpath.basename(ref.replace("\\", "/")) or doc.type
    # storage names are "<document_id>_<original name>"; show only the original
    return re.sub(r"^[0-9a-fA-F-]{36}_", "", name)


def _item_out(r: PlanItemRow) -> PlanItem:
    return PlanItem(
        item_id=r.item_id, type=r.type, objective_id=r.objective_id, skill_id=r.skill_id, resource_id=r.resource_id,
        practice_item_ids=r.practice_item_ids, est_minutes=r.est_minutes, difficulty=r.difficulty, day_slot=r.day_slot,
        depends_on=r.depends_on, reason=PlanItemReason(**r.reason) if r.reason else PlanItemReason(), status=r.status,
    )


# -- Catalog -------------------------------------------------------------------


@router.get("/roles", response_model=list[RoleOut])
async def list_roles(session: AsyncSession = Depends(get_session)) -> list[RoleOut]:
    catalog = CatalogRepository(session)
    roles = await catalog.get_all_roles()
    requirements = await catalog.get_all_role_requirements()
    counts: dict[str, int] = {}
    for req in requirements:
        counts[req.role_id] = counts.get(req.role_id, 0) + 1
    return [
        RoleOut(role_id=r.role_id, title=r.title, description=r.description or "", required_skill_count=counts.get(r.role_id, 0))
        for r in roles
    ]


@router.get("/catalog/skills", response_model=list[SkillOut])
async def list_skills(ids: str | None = None, session: AsyncSession = Depends(get_session)) -> list[SkillOut]:
    wanted = _split_ids(ids)
    stmt = select(Skill)
    if wanted:
        stmt = stmt.where(Skill.skill_id.in_(wanted))
    rows = (await session.execute(stmt.order_by(Skill.label))).scalars().all()
    return [_skill_out(s) for s in rows]


@router.get("/catalog/resources", response_model=list[ResourceOut])
async def list_resources(
    ids: str = Query(min_length=1), session: AsyncSession = Depends(get_session)
) -> list[ResourceOut]:
    wanted = _split_ids(ids)
    rows = await CatalogRepository(session).get_resources_by_ids(wanted)
    return [_resource_out(r) for r in rows]


# -- Learner views ---------------------------------------------------------------


@router.get("/learners/me/profile", response_model=LearnerProfileOut)
async def get_profile(
    learner_id: str = Depends(get_current_learner_id), session: AsyncSession = Depends(get_session)
) -> LearnerProfileOut:
    repo = ProfilingRepository(session)
    profile = await repo.get_learner_profile(learner_id)
    if profile is None:  # unreachable: learner_id is resolved from the profile
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No learner profile yet")
    states = await repo.list_skill_states_for_learner(learner_id)
    return LearnerProfileOut(
        learner_id=profile.learner_id, target_role_id=profile.target_role_id, career_goal=profile.career_goal,
        experience_summary=profile.experience_summary, weekly_hours=profile.weekly_hours,
        preferences=profile.preferences, constraints=profile.constraints, mapped_skill_count=len(states),
    )


async def _evidence_out(session: AsyncSession, learner_id: str, skill_id: str | None = None) -> list[EvidenceOut]:
    repo = ProfilingRepository(session)
    rows = await repo.list_evidence_for_learner(learner_id)
    if skill_id is not None:
        rows = [e for e in rows if e.skill_id == skill_id]
    skills = {s.skill_id: s.label for s in await CatalogRepository(session).get_all_skills()}
    docs: dict[str, Document | None] = {}
    out: list[EvidenceOut] = []
    for e in rows:
        if e.document_id and e.document_id not in docs:
            docs[e.document_id] = await repo.get_document(e.document_id)
        out.append(
            EvidenceOut(
                evidence_id=e.evidence_id, skill_id=e.skill_id, skill_label=skills.get(e.skill_id, e.skill_id),
                tier=e.tier, source_type=e.source_type, document_id=e.document_id,
                document_label=_document_label(docs.get(e.document_id)) if e.document_id else None,
                span_text=e.span_text or "", span_offsets=e.span_offsets, verified=e.verified,
                created_at=e.created_at.isoformat() if e.created_at else "",
            )
        )
    return out


@router.get("/learners/me/evidence", response_model=list[EvidenceOut])
async def list_evidence(
    learner_id: str = Depends(get_current_learner_id), session: AsyncSession = Depends(get_session)
) -> list[EvidenceOut]:
    return await _evidence_out(session, learner_id)


@router.get("/learners/me/skills/{skill_id}", response_model=SkillDetailOut)
async def get_skill_detail(
    skill_id: str,
    learner_id: str = Depends(get_current_learner_id),
    session: AsyncSession = Depends(get_session),
    graph: SkillGraphService = Depends(get_skill_graph_service),
) -> SkillDetailOut:
    catalog = CatalogRepository(session)
    repo = ProfilingRepository(session)
    skill = (await session.execute(select(Skill).where(Skill.skill_id == skill_id))).scalar_one_or_none()
    if skill is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="unknown skill_id")
    labels = {s.skill_id: s.label for s in await catalog.get_all_skills()}

    profile = await repo.get_learner_profile(learner_id)
    role_id = profile.target_role_id if profile else None
    states = await repo.list_skill_states_for_learner(learner_id)
    evidence_rows = await repo.list_evidence_for_learner(learner_id)

    gap_by_skill: dict[str, SkillGap] = {}
    if role_id:
        try:
            result = analyze_gaps(
                role_id,
                [LearnerSkillRecord(skill_id=s.skill_id, alpha=s.alpha, beta=s.beta, tier_max=s.tier_max, n_obs=s.n_obs) for s in states],
                [EvidenceRecord(evidence_id=e.evidence_id, skill_id=e.skill_id, tier=e.tier) for e in evidence_rows],
                graph,
            )
            gap_by_skill = {
                g.skill_id: SkillGap(
                    skill_id=g.skill_id, label=g.label, status=g.status, gap_type=g.gap_type, required_level=g.required_level,
                    current_level=g.current_level, blocked_by=g.blocked_by, root_of=g.root_of, priority=g.priority,
                    ordering_layer=g.ordering_layer, evidence_ids=g.evidence_ids, audit_flags=g.audit_flags,
                )
                for g in result.gaps
            }
        except UnknownRoleError:
            gap_by_skill = {}

    state = next((s for s in states if s.skill_id == skill_id), None)
    mastery = None
    if state is not None:
        total = state.alpha + state.beta
        mastery = MasteryOut(
            estimate=round(state.alpha / total, 4) if total else 0.0,
            band=state.band, confidence=state.confidence, tier_max=state.tier_max, n_obs=state.n_obs,
        )

    requirement = None
    if role_id:
        req = (
            await session.execute(
                select(RoleRequirement).where(RoleRequirement.role_id == role_id, RoleRequirement.skill_id == skill_id)
            )
        ).scalar_one_or_none()
        if req is not None:
            requirement = RoleRequirementOut(role_id=role_id, required_level=req.required_level, weight=req.weight)

    levels = dict(graph.hard_prerequisite_out_edges(skill_id))

    def _rel(ids: list[str], with_level: bool) -> list[PrerequisiteOut]:
        return [
            PrerequisiteOut(
                skill_id=i, label=labels.get(i, i), status=gap_by_skill[i].status if i in gap_by_skill else None,
                min_level=levels.get(i) if with_level else None,
            )
            for i in ids
        ]

    prereq_ids = graph.direct_prerequisites(skill_id, include_soft=False)
    dependent_ids = graph.direct_dependents(skill_id, include_soft=False)

    targeting = await catalog.get_resources_targeting_skill(skill_id)
    target_level = (gap_by_skill[skill_id].current_level + 1) if skill_id in gap_by_skill else 1
    ranked = sorted(
        targeting,
        key=lambda pair: (
            0 if pair[1].level_from <= target_level <= pair[1].level_to else 1,
            0 if pair[0].link_status == "ok" else 1,
            pair[0].difficulty,
        ),
    )[:4]

    assess_repo = AssessmentRepository(session)
    misconceptions: list[MisconceptionOut] = []
    for m in await catalog.get_misconceptions_for_skill(skill_id):
        lm = await assess_repo.get_learner_misconception(learner_id, m.misconception_id)
        misconceptions.append(
            MisconceptionOut(
                misconception_id=m.misconception_id, description=m.description or "", signature=m.signature or "",
                root_skill_id=m.root_skill_id, root_skill_label=labels.get(m.root_skill_id, m.root_skill_id),
                learner_status=lm.status if lm else None,
            )
        )

    plan_items: list[SkillPlanItemOut] = []
    plan_repo = PlanningRepository(session)
    plan_row = await plan_repo.get_current_plan_for_learner(learner_id)
    if plan_row is not None and plan_row.current_revision_id:
        for r in await plan_repo.list_items_for_revision(plan_row.current_revision_id):
            if r.skill_id == skill_id:
                plan_items.append(
                    SkillPlanItemOut(item_id=r.item_id, type=r.type, status=r.status, day_slot=r.day_slot, est_minutes=r.est_minutes)
                )

    return SkillDetailOut(
        skill=_skill_out(skill),
        gap=gap_by_skill.get(skill_id),
        mastery=mastery,
        role_requirement=requirement,
        evidence=await _evidence_out(session, learner_id, skill_id),
        prerequisites=_rel(prereq_ids, True),
        dependents=_rel([d for d in dependent_ids if not gap_by_skill or d in gap_by_skill], False),
        resources=[_resource_out(r) for r, _ in ranked],
        misconceptions=misconceptions,
        plan_items=plan_items,
    )


# -- Plan revisions ----------------------------------------------------------------


def _revision_out(rev: PlanRevision, current_id: str | None, decision_by_output: dict[str, str]) -> PlanRevisionOut:
    return PlanRevisionOut(
        revision_id=rev.revision_id, plan_id=rev.plan_id, revision_no=rev.revision_no,
        parent_revision_id=rev.parent_revision_id, cause_type=rev.cause_type, cause_ref=rev.cause_ref or "",
        operators=rev.operators or [], diff=rev.diff or {}, degraded=rev.degraded, overall_reason=rev.overall_reason or "",
        created_at=rev.created_at.isoformat() if rev.created_at else "", reverted_by=rev.reverted_by,
        is_current=rev.revision_id == current_id, decision_id=decision_by_output.get(rev.revision_id),
    )


@router.get("/learners/me/plans/current/revisions", response_model=list[PlanRevisionOut])
async def list_current_plan_revisions(
    learner_id: str = Depends(get_current_learner_id), session: AsyncSession = Depends(get_session)
) -> list[PlanRevisionOut]:
    plan_repo = PlanningRepository(session)
    plan_row = await plan_repo.get_current_plan_for_learner(learner_id)
    if plan_row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No plan yet")
    decisions = await ReflectionRepository(session).list_decision_records(learner_id, type_="reflection")
    decision_by_output = {d.output_ref: d.decision_id for d in decisions if d.output_ref}
    revisions = await plan_repo.list_revisions(plan_row.plan_id)
    return [_revision_out(r, plan_row.current_revision_id, decision_by_output) for r in revisions]


@router.get("/learners/me/plans/{plan_id}/revisions/{revision_id}", response_model=PlanRevisionDetailOut)
async def get_plan_revision(
    plan_id: str,
    revision_id: str,
    learner_id: str = Depends(get_current_learner_id),
    session: AsyncSession = Depends(get_session),
) -> PlanRevisionDetailOut:
    plan_repo = PlanningRepository(session)
    plan_row = await plan_repo.get_plan(plan_id)
    revision = await plan_repo.get_revision(revision_id)
    if plan_row is None or plan_row.learner_id != learner_id or revision is None or revision.plan_id != plan_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="unknown revision")
    decisions = await ReflectionRepository(session).list_decision_records(learner_id, type_="reflection")
    decision_by_output = {d.output_ref: d.decision_id for d in decisions if d.output_ref}
    base = _revision_out(revision, plan_row.current_revision_id, decision_by_output)
    items = [_item_out(r) for r in await plan_repo.list_items_for_revision(revision_id)]
    return PlanRevisionDetailOut(**base.model_dump(), items=items)


@router.patch("/learners/me/plans/items/{item_id}", response_model=PlanItem)
async def update_plan_item(
    item_id: str,
    body: UpdatePlanItemRequest,
    learner_id: str = Depends(get_current_learner_id),
    session: AsyncSession = Depends(get_session),
) -> PlanItem:
    """Marks an item of the learner's *current* revision planned/done/skipped.
    Superseded revisions are history and are never edited."""
    plan_repo = PlanningRepository(session)
    plan_row = await plan_repo.get_current_plan_for_learner(learner_id)
    if plan_row is None or plan_row.current_revision_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No plan yet")
    row = (
        await session.execute(
            select(PlanItemRow).where(PlanItemRow.item_id == item_id, PlanItemRow.revision_id == plan_row.current_revision_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="unknown plan item")
    row.status = body.status
    await session.commit()
    return _item_out(row)
