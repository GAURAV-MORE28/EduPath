"""The Tutor Agent's read-only tool inventory (design §8.2, §23.1, §26.2).

Every tool takes the shared per-turn `TutorContext` (never `learner_id` as an
argument the LLM could substitute — ARCHITECTURE_CONTRACTS.md §7) and returns
a `ToolCallResult`: the data block(s) the compose-answer prompt will show the
LLM, plus `citable_ids` — the *only* IDs an answer built from this tool call
may cite (`app/provenance/citations.py` enforces this after the fact). No
tool here can mutate anything (`commit_*` tools are never in this inventory,
ARCHITECTURE_CONTRACTS.md §13) and none of them ever invents an ID — every
value in `citable_ids` is copied from a real row/graph node this call just
read.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.core.thresholds import TUTOR_SEARCH_RESOURCES_TOP_K
from app.graph.queries import PathStep, UnknownSkillError
from app.tutor.context import TutorContext
from app.tutor.report_builder import ProgressReportData, compute_progress_report


@dataclass
class ToolCallResult:
    tool: str
    args: dict[str, Any]
    data: dict[str, Any]
    citable_ids: set[str] = field(default_factory=set)
    error: str | None = None


# Bound what a tool hands the model: a full role has ~50 gaps / ~25 skill states, which exceeds a small
# per-request token limit (observed: Groq answered 413 "request too large") and buries the answer. The tools
# return the highest-signal rows plus the true totals, and only IDs actually shown are citable.
MAX_GAPS_SHOWN = 12
MAX_STRENGTHS_SHOWN = 8
MAX_SKILL_STATES_SHOWN = 20
MAX_EVIDENCE_IDS_PER_ROW = 3


class UnknownToolError(Exception):
    pass


async def get_learner_state(ctx: TutorContext) -> ToolCallResult:
    profile = await ctx.profiling_repo.get_learner_profile(ctx.learner_id)
    skill_states = await ctx.profiling_repo.list_skill_states_for_learner(ctx.learner_id)

    citable_ids = {ctx.role_id}
    skills: dict[str, dict[str, Any]] = {}
    ranked = sorted(skill_states, key=lambda st: (st.alpha / (st.alpha + st.beta) if st.alpha + st.beta else 0.0), reverse=True)
    for s in ranked[:MAX_SKILL_STATES_SHOWN]:
        total = s.alpha + s.beta
        skills[s.skill_id] = {
            "band": s.band,
            "tier_max": s.tier_max,
            "n_obs": s.n_obs,
            "mastery": round(s.alpha / total, 3) if total > 0 else 0.0,
        }
        citable_ids.add(s.skill_id)

    data = {
        "learner_id": ctx.learner_id,
        "target_role_id": ctx.role_id,
        "weekly_hours": profile.weekly_hours if profile else None,
        "career_goal": profile.career_goal if profile else "",
        "graph_version": ctx.graph.graph_version,
        "skills": skills,
        "skills_total": len(skill_states),
    }
    return ToolCallResult(tool="get_learner_state", args={}, data=data, citable_ids=citable_ids)


async def get_gaps(ctx: TutorContext) -> ToolCallResult:
    result = ctx.gap_result
    citable_ids: set[str] = set()

    open_gaps = sorted((g for g in result.gaps if g.status != "MET"), key=lambda g: -g.priority)
    gaps_out = []
    for g in open_gaps[:MAX_GAPS_SHOWN]:
        evidence = g.evidence_ids[:MAX_EVIDENCE_IDS_PER_ROW]
        blocked_by = g.blocked_by[:MAX_EVIDENCE_IDS_PER_ROW]
        citable_ids.add(g.skill_id)
        citable_ids.update(evidence)
        citable_ids.update(blocked_by)
        gaps_out.append(
            {
                "skill_id": g.skill_id, "label": g.label, "status": g.status, "gap_type": g.gap_type,
                "required_level": g.required_level, "current_level": g.current_level,
                "blocked_by": blocked_by, "priority": round(g.priority, 3), "evidence_ids": evidence,
            }
        )

    strengths_out = []
    for s in result.strengths[:MAX_STRENGTHS_SHOWN]:
        evidence = s.evidence_ids[:MAX_EVIDENCE_IDS_PER_ROW]
        citable_ids.add(s.skill_id)
        citable_ids.update(evidence)
        strengths_out.append({"skill_id": s.skill_id, "label": s.label, "mastery": s.mastery, "evidence_ids": evidence})

    data = {
        "role_id": result.role_id, "graph_version": result.graph_version,
        "gaps": gaps_out, "open_gaps_total": len(open_gaps), "open_gaps_shown": len(gaps_out),
        "strengths": strengths_out, "strengths_total": len(result.strengths),
    }
    return ToolCallResult(tool="get_gaps", args={}, data=data, citable_ids=citable_ids)


async def get_current_plan(ctx: TutorContext) -> ToolCallResult:
    plan_row = await ctx.planning_repo.get_current_plan_for_learner(ctx.learner_id)
    if plan_row is None or plan_row.current_revision_id is None:
        return ToolCallResult(tool="get_current_plan", args={}, data={"plan": None}, error="no plan yet")

    revision = await ctx.planning_repo.get_revision(plan_row.current_revision_id)
    item_rows = await ctx.planning_repo.list_items_for_revision(plan_row.current_revision_id)

    citable_ids = {plan_row.plan_id}
    if revision is not None:
        citable_ids.add(revision.revision_id)

    items_out = []
    for r in item_rows:
        citable_ids.update({r.item_id, r.skill_id, r.objective_id})
        if r.resource_id:
            citable_ids.add(r.resource_id)
        reason = r.reason or {}
        citable_ids.update(reason.get("evidence_ids") or [])
        if reason.get("decision_id"):
            citable_ids.add(reason["decision_id"])
        items_out.append(
            {
                "item_id": r.item_id, "type": r.type, "objective_id": r.objective_id, "skill_id": r.skill_id,
                "resource_id": r.resource_id, "est_minutes": r.est_minutes, "day_slot": r.day_slot,
                "status": r.status, "reason": reason,
            }
        )

    data = {
        "plan_id": plan_row.plan_id, "week_index": plan_row.week_index,
        "revision_id": revision.revision_id if revision else None,
        "revision_no": revision.revision_no if revision else None,
        "overall_reason": revision.overall_reason if revision else "",
        "degraded": revision.degraded if revision else False,
        "items": items_out,
    }
    return ToolCallResult(tool="get_current_plan", args={}, data=data, citable_ids=citable_ids)


async def get_revisions(ctx: TutorContext) -> ToolCallResult:
    plan_row = await ctx.planning_repo.get_current_plan_for_learner(ctx.learner_id)
    if plan_row is None:
        return ToolCallResult(tool="get_revisions", args={}, data={"revisions": []}, error="no plan yet")

    revisions = await ctx.planning_repo.list_revisions(plan_row.plan_id)
    citable_ids = {plan_row.plan_id}
    out = []
    for r in revisions:
        citable_ids.add(r.revision_id)
        out.append(
            {
                "revision_id": r.revision_id, "revision_no": r.revision_no,
                "parent_revision_id": r.parent_revision_id, "cause_type": r.cause_type,
                "cause_ref": r.cause_ref, "operators": r.operators, "degraded": r.degraded,
                "overall_reason": r.overall_reason, "reverted_by": r.reverted_by,
            }
        )
    data = {"plan_id": plan_row.plan_id, "revisions": out}
    return ToolCallResult(tool="get_revisions", args={}, data=data, citable_ids=citable_ids)


async def get_evidence(ctx: TutorContext, *, skill_id: str) -> ToolCallResult:
    try:
        ctx.graph.get_skill(skill_id)
    except UnknownSkillError:
        return ToolCallResult(tool="get_evidence", args={"skill_id": skill_id}, data={"evidence": []}, error="unknown skill_id")

    all_evidence = await ctx.profiling_repo.list_evidence_for_learner(ctx.learner_id)
    rows = [e for e in all_evidence if e.skill_id == skill_id]
    citable_ids = {skill_id}
    out = []
    for e in rows:
        citable_ids.add(e.evidence_id)
        out.append(
            {
                "evidence_id": e.evidence_id, "tier": e.tier, "source_type": e.source_type,
                "span_text": e.span_text, "verified": e.verified,
            }
        )
    data = {"skill_id": skill_id, "evidence": out}
    return ToolCallResult(tool="get_evidence", args={"skill_id": skill_id}, data=data, citable_ids=citable_ids)


async def explain_skill_path(ctx: TutorContext, *, skill_id: str) -> ToolCallResult:
    try:
        path: list[PathStep] | None = ctx.graph.explain_skill_path(skill_id, ctx.role_id)
    except UnknownSkillError:
        return ToolCallResult(tool="explain_skill_path", args={"skill_id": skill_id}, data={"path": None}, error="unknown skill_id")

    if path is None:
        return ToolCallResult(
            tool="explain_skill_path", args={"skill_id": skill_id}, data={"skill_id": skill_id, "path": None},
            citable_ids={skill_id}, error="no hard-prerequisite path from this skill to a role-required skill",
        )

    path_id = ">".join(step.skill_id for step in path)
    citable_ids = {step.skill_id for step in path} | {path_id}
    data = {
        "skill_id": skill_id, "role_id": ctx.role_id, "path_id": path_id,
        "path": [{"skill_id": s.skill_id, "label": s.label} for s in path],
    }
    return ToolCallResult(tool="explain_skill_path", args={"skill_id": skill_id}, data=data, citable_ids=citable_ids)


async def search_resources(ctx: TutorContext, *, skill_id: str) -> ToolCallResult:
    gaps_by_skill = {g.skill_id: g for g in ctx.gap_result.gaps}
    current_level = gaps_by_skill[skill_id].current_level if skill_id in gaps_by_skill else 0
    # Same eligibility input the Planner uses (app/planning/candidates.py): a resource whose own
    # prerequisites the learner has met must not be filtered out. Omitting this made every
    # resource with a prerequisite "ineligible" -> "0 catalog resource(s) found" (Phase 12 fix).
    met_skill_ids = {g.skill_id for g in ctx.gap_result.gaps if g.status == "MET"}
    try:
        recs = await ctx.retrieval_service.recommend_for_skill(
            skill_id=skill_id, current_level=current_level, met_skill_ids=met_skill_ids, top_k=TUTOR_SEARCH_RESOURCES_TOP_K
        )
    except UnknownSkillError:
        return ToolCallResult(tool="search_resources", args={"skill_id": skill_id}, data={"resources": []}, error="unknown skill_id")

    resources_by_id = {r.resource_id: r for r in await ctx.catalog.get_resources_by_ids([r.resource_id for r in recs])}
    citable_ids = {skill_id}
    out = []
    for r in recs:
        citable_ids.add(r.resource_id)
        resource = resources_by_id.get(r.resource_id)
        out.append(
            {
                "resource_id": r.resource_id, "score": r.score, "score_breakdown": r.score_breakdown,
                "title": resource.title if resource else "", "url": resource.url if resource else "",
                "provider": resource.provider if resource else "",
            }
        )
    data = {"skill_id": skill_id, "resources": out}
    return ToolCallResult(tool="search_resources", args={"skill_id": skill_id}, data=data, citable_ids=citable_ids)


def progress_report_to_tool_result(report: ProgressReportData) -> ToolCallResult:
    """Shapes a `ProgressReportData` (`app/tutor/report_builder.py`) into the
    same ID-labeled `ToolCallResult` block the `get_progress` tool returns —
    shared with `app/tutor/service.py::narrate_progress` (design's "Report
    Builder + Tutor narration", `GET /api/learners/me/progress`) so the two
    callers never independently invent two different notions of "which IDs
    are citable from a progress report"."""
    citable_ids: set[str] = set()
    for entry in report.acquired + report.in_progress:
        citable_ids.add(entry.skill_id)
        citable_ids.update(entry.evidence_ids)
    for g in report.remaining_gaps:
        citable_ids.add(g.skill_id)
    for sa in report.struggle_areas:
        citable_ids.add(sa.skill_id)
        if sa.signal_id:
            citable_ids.add(sa.signal_id)
        if sa.misconception_id:
            citable_ids.add(sa.misconception_id)
    for act in report.completed_work + report.next_steps:
        citable_ids.update({act.item_id, act.skill_id})

    data = {
        "period": report.period,
        "acquired": [{"skill_id": s.skill_id, "label": s.label, "mastery": s.mastery} for s in report.acquired],
        "in_progress": [{"skill_id": s.skill_id, "label": s.label, "band": s.band} for s in report.in_progress],
        "remaining_gaps": [{"skill_id": g.skill_id, "label": g.label, "status": g.status} for g in report.remaining_gaps],
        "struggle_areas": [
            {"skill_id": sa.skill_id, "status": sa.status, "signal_class": sa.signal_class, "misconception_id": sa.misconception_id}
            for sa in report.struggle_areas
        ],
        "completed_work": [{"item_id": a.item_id, "skill_id": a.skill_id, "type": a.type} for a in report.completed_work],
        "next_steps": [{"item_id": a.item_id, "skill_id": a.skill_id, "type": a.type, "day_slot": a.day_slot} for a in report.next_steps],
    }
    return ToolCallResult(tool="get_progress", args={"period": report.period}, data=data, citable_ids=citable_ids)


async def get_progress(ctx: TutorContext, *, period: str = "all_time") -> ToolCallResult:
    report = await compute_progress_report(ctx, period=period)
    return progress_report_to_tool_result(report)


async def get_decision(ctx: TutorContext, *, decision_id: str) -> ToolCallResult:
    record = await ctx.reflection_repo.get_decision_record(ctx.learner_id, decision_id)
    if record is None:
        return ToolCallResult(tool="get_decision", args={"decision_id": decision_id}, data={"decision": None}, error="unknown decision_id")

    citable_ids = {record.decision_id}
    citable_ids.update(record.evidence_ids)
    for path in record.graph_paths:
        citable_ids.update(path)
    if record.output_ref:
        citable_ids.add(record.output_ref)

    data = {
        "decision_id": record.decision_id, "type": record.type, "inputs": record.inputs,
        "evidence_ids": record.evidence_ids, "graph_paths": record.graph_paths, "rules_fired": record.rules_fired,
        "scores": record.scores, "graph_version": record.graph_version, "output_ref": record.output_ref,
    }
    return ToolCallResult(tool="get_decision", args={"decision_id": decision_id}, data=data, citable_ids=citable_ids)


TOOL_REGISTRY = {
    "get_learner_state": get_learner_state,
    "get_gaps": get_gaps,
    "get_current_plan": get_current_plan,
    "get_revisions": get_revisions,
    "get_evidence": get_evidence,
    "explain_skill_path": explain_skill_path,
    "search_resources": search_resources,
    "get_progress": get_progress,
    "get_decision": get_decision,
}


async def call_tool(ctx: TutorContext, tool: str, args: dict[str, Any]) -> ToolCallResult:
    """Dispatch one bounded tool call, never raising — an unexpected error
    (e.g. a hallucinated `skill_id` the graph doesn't have) degrades to an
    empty, uncitable result rather than crashing the chat turn."""
    fn = TOOL_REGISTRY.get(tool)
    if fn is None:
        raise UnknownToolError(f"unknown tool: {tool!r}")
    try:
        return await fn(ctx, **args)
    except Exception as exc:  # noqa: BLE001 — a tool must never crash the chat turn (design P7)
        return ToolCallResult(tool=tool, args=args, data={}, error=str(exc))
