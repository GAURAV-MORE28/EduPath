"""LangGraph orchestration skeleton.

Design §9.1: four graphs (G1 Onboarding, G2 Planning, G3 Evidence-Response,
G4 Tutor), each an explicit LangGraph state machine — never a free-form
agent loop (ARCHITECTURE_CONTRACTS.md: "Explicit state over emergent
behavior"). Phase 1 built the orchestration framework and a trivial
`bootstrap` graph used only to prove LangGraph compiles and runs in this
process. G1 Onboarding is implemented below (Phase 2 — Learner Profiling);
G2/G3/G4's real nodes are built by the phases that own them (5, 8, 9).
"""
from __future__ import annotations

import base64
from typing import Any

from langgraph.graph import END, StateGraph

from app.agents.planner import PlannerAgent
from app.agents.profiler import ProfilerAgent
from app.agents.tutor import TutorAgent
from app.core.thresholds import (
    DEFAULT_SESSION_CAP_MINUTES,
    NEW_SKILL_CONCURRENCY_CAP,
    PLANNER_MAX_DRAFT_ATTEMPTS,
    TUTOR_MAX_COMPOSE_ATTEMPTS,
)
from app.gap.engine import GapAnalysisResult, analyze_gaps
from app.gateway.vlm_gateway import VLMGateway, VLMPageReadRequest
from app.graph.queries import SkillGraphService
from app.orchestration.state import RunState
from app.planning.candidates import ObjectiveCandidateSet, build_candidate_sets
from app.planning.fallback import FALLBACK_OVERALL_REASON, build_fallback_plan
from app.planning.validator import validate_plan
from app.profiling.document_parser import extract_text
from app.profiling.evidence_verifier import EvidenceVerifier
from app.profiling.pii import scrub_pii
from app.profiling.skill_normalizer import SkillNormalizer
from app.provenance.citations import verify_citations
from app.repositories.catalog_repository import CatalogRepository
from app.retrieval.service import ResourceRetrievalService
from app.schemas.common import PlanItem, PlanItemReason
from app.schemas.profiling import ExtractedClaim, VerifiedClaim
from app.tutor.conservative import build_conservative_answer
from app.tutor.context import TutorContext
from app.tutor.intent import OUT_OF_SCOPE, classify_intent, plan_tools
from app.tutor.tools import ToolCallResult, call_tool


async def _start_node(state: RunState) -> dict[str, Any]:
    return {"status": "running"}


async def _finish_node(state: RunState) -> dict[str, Any]:
    return {"status": "completed"}


def build_bootstrap_graph():
    """A minimal two-node graph with no business logic, used by the startup
    health check and the LangGraph initialization test to prove the
    orchestration framework (state schema, compilation, execution) works."""
    graph = StateGraph(RunState)
    graph.add_node("start", _start_node)
    graph.add_node("finish", _finish_node)
    graph.set_entry_point("start")
    graph.add_edge("start", "finish")
    graph.add_edge("finish", END)
    return graph.compile()


async def _render_pdf_first_page_png(content: bytes) -> bytes | None:
    import pymupdf

    try:
        pdf = pymupdf.open(stream=content, filetype="pdf")
    except Exception:  # noqa: BLE001 - unreadable PDF, nothing to render for the VLM
        return None
    try:
        if pdf.page_count == 0:
            return None
        return pdf[0].get_pixmap().tobytes("png")
    finally:
        pdf.close()


def build_onboarding_graph(
    *,
    profiler_agent: ProfilerAgent,
    evidence_verifier: EvidenceVerifier,
    skill_normalizer: SkillNormalizer,
    vlm_gateway: VLMGateway,
):
    """G1 Onboarding (design §9.3): `parse_documents -> extract_claims
    (Profiler) -> verify_evidence -> normalize_skills`. Terminates at
    `status="needs_user"` — `user_confirm` and `gap_analysis` (design's next
    two nodes) are not part of this graph: `gap_analysis` is explicitly out
    of this phase's scope (Phase 4, Gap Engine, not implemented), and
    `user_confirm` is a separate, later HTTP request
    (`POST /api/learners/me/claims/confirm`) rather than an in-graph pause —
    Phase 1 did not build a Postgres-backed LangGraph checkpointer to
    resume a paused run across requests (see IMPLEMENTATION_STATE.md "Known
    Issues"), so the hand-off goes through `PendingClaim` rows
    (`app/db/models.py`) instead. See Contract Changes for this scope
    decision.

    Runs one document (or one GitHub-derived pseudo-document) per invocation
    -- `POST /api/learners/me/documents` accepts one file per call; uploading
    several files means several calls/runs, not one run over a batch. See
    Contract Changes.

    Expects `state["data"]` to already contain: `learner_id`, `document_id`,
    `doc_type` (`pdf`/`docx`/`text`/`image`/`github`), and either
    `raw_content_b64` (base64 of the uploaded file bytes) or, for
    `doc_type == "github"`, `github_summary_text` (a pre-built synthetic
    summary — see `app/profiling/onboarding.py`) and `is_github_source=True`.
    """

    async def parse_documents_node(state: RunState) -> dict[str, Any]:
        d = dict(state["data"])
        doc_type = d["doc_type"]

        if doc_type == "github":
            raw_text = d.get("github_summary_text") or ""
            parse_status = "parsed" if raw_text.strip() else "empty"
        else:
            content = base64.b64decode(d["raw_content_b64"])
            extraction = extract_text(doc_type, content)
            raw_text = extraction.text
            parse_status = "parsed"
            if extraction.needs_vlm_fallback:
                vlm_text = await _vlm_fallback(doc_type, content, d["document_id"], vlm_gateway)
                if vlm_text:
                    raw_text = vlm_text
                    parse_status = "parsed_vlm"
                else:
                    # design §30: "still empty -> ask user to paste text; continue with
                    # intake-only claims" -- the run continues (0 claims from this doc),
                    # it does not hard-fail.
                    parse_status = "needs_text_paste"

        scrubbed_text, _redactions = scrub_pii(raw_text)
        d["source_text"] = scrubbed_text
        d["parse_status"] = parse_status
        return {"data": d, "status": "running"}

    async def extract_claims_node(state: RunState) -> dict[str, Any]:
        d = dict(state["data"])
        result = await profiler_agent.run(
            state["run_id"], {"document_text": d["source_text"], "source_doc_id": d["document_id"]}
        )
        d["claims_raw"] = result["claims"]
        d["extraction_degraded"] = result["degraded"]
        return {"data": d}

    async def verify_evidence_node(state: RunState) -> dict[str, Any]:
        d = dict(state["data"])
        claims = [ExtractedClaim.model_validate(c) for c in d["claims_raw"]]
        verified = evidence_verifier.verify_all(
            claims, d["source_text"], is_github_source=d.get("is_github_source", False)
        )
        kept = [v for v in verified if v.span_verified and not v.injection_flagged]
        d["verified_claims"] = [v.model_dump(mode="json") for v in kept]
        d["dropped_unverified"] = sum(1 for v in verified if not v.span_verified)
        d["dropped_injection"] = sum(1 for v in verified if v.span_verified and v.injection_flagged)
        return {"data": d}

    async def normalize_skills_node(state: RunState) -> dict[str, Any]:
        d = dict(state["data"])
        verified = [VerifiedClaim.model_validate(v) for v in d["verified_claims"]]
        normalized = [await skill_normalizer.normalize(v) for v in verified]
        d["normalized_claims"] = [n.model_dump(mode="json") for n in normalized]
        # design §9.3: on success -> user_confirm (a separate request in this
        # implementation, see the graph's docstring) -- the run pauses here.
        return {"data": d, "status": "needs_user"}

    graph = StateGraph(RunState)
    graph.add_node("parse_documents", parse_documents_node)
    graph.add_node("extract_claims", extract_claims_node)
    graph.add_node("verify_evidence", verify_evidence_node)
    graph.add_node("normalize_skills", normalize_skills_node)
    graph.set_entry_point("parse_documents")
    graph.add_edge("parse_documents", "extract_claims")
    graph.add_edge("extract_claims", "verify_evidence")
    graph.add_edge("verify_evidence", "normalize_skills")
    graph.add_edge("normalize_skills", END)
    return graph.compile()


async def _vlm_fallback(doc_type: str, content: bytes, document_id: str, vlm_gateway: VLMGateway) -> str:
    """design §22.1: "if empty or image -> VLM page reads". Only PDFs (render
    page 1 to PNG) and raw images have a page image to send; DOCX/text with
    no extractable text have nothing to render, so they skip straight to
    "needs_text_paste" (design §30)."""
    if doc_type == "pdf":
        png_bytes = await _render_pdf_first_page_png(content)
        if png_bytes is None:
            return ""
        image_bytes = png_bytes
    elif doc_type == "image":
        image_bytes = content
    else:
        return ""

    response = await vlm_gateway.read_page(
        VLMPageReadRequest(document_id=document_id, image_bytes_b64=base64.b64encode(image_bytes).decode("ascii"))
    )
    return "" if response.degraded else response.text


def _drafts_to_plan_items(raw_items: list[dict]) -> list[PlanItem]:
    return [
        PlanItem(
            item_id=r["item_id"],
            type=r["type"],
            objective_id=r["objective_id"],
            skill_id=r["skill_id"],
            resource_id=r.get("resource_id"),
            practice_item_ids=list(r.get("practice_item_ids") or []),
            est_minutes=r["est_minutes"],
            difficulty=r["difficulty"],
            day_slot=r["day_slot"],
            depends_on=list(r.get("depends_on") or []),
            reason=PlanItemReason(text=r.get("reason_text", "")),
        )
        for r in raw_items
    ]


def build_planning_graph(
    *,
    graph_service: SkillGraphService,
    planner_agent: PlannerAgent,
    catalog: CatalogRepository,
    retrieval_service: ResourceRetrievalService,
):
    """G2 Planning (design §9.4): `build_objectives (Gap Engine) ->
    retrieve_candidates (Retriever/Ranker) -> plan_draft (Planner) ->
    validate_plan (Validator) -> [loop to plan_draft, attempt <=
    PLANNER_MAX_DRAFT_ATTEMPTS] -> fallback_plan (if still failing/LLM
    degraded)`.

    Does **not** include design's `critique` node (Reflection mode a,
    plan-critique) or a DB-writing `commit_plan` node: Reflection is Phase 8
    (not implemented), and this graph -- like G1 Onboarding before it --
    stops at a finalized-in-memory result; the actual `WeeklyPlan`/
    `PlanRevision`/`PlanItem` persistence is orchestration glue outside the
    graph (`app/planning/service.py`), the same split Phase 2's
    `app/profiling/onboarding.py` already uses for `PendingClaim` writes.

    Expects `state["data"]` to already contain: `role_id`, `skill_records`
    (`list[LearnerSkillRecord]`), `evidence_records` (`list[EvidenceRecord]`,
    both Phase 4's plain record types), `hours_budget_minutes`, and
    optionally `mode` (`"draft"` default, or `"patch"`), `existing_items`,
    `operators`, `modality_order`, `language`, `session_cap_minutes`,
    `new_skill_cap`. Terminates with `status="completed"` and
    `state["data"]["final_items"]`/`final_overall_reason`/`final_degraded"`
    populated either way (LLM-validated draft, or the always-valid Fallback
    Planner) -- ARCHITECTURE_CONTRACTS.md §10: "a demo/run can never fail to
    produce a plan."
    """

    async def build_objectives_node(state: RunState) -> dict[str, Any]:
        d = dict(state["data"])
        result: GapAnalysisResult = analyze_gaps(d["role_id"], d["skill_records"], d["evidence_records"], graph_service)
        d["gap_result"] = result
        return {"data": d, "status": "running"}

    async def retrieve_candidates_node(state: RunState) -> dict[str, Any]:
        d = dict(state["data"])
        candidate_sets: dict[str, ObjectiveCandidateSet] = await build_candidate_sets(
            gap_result=d["gap_result"],
            retrieval_service=retrieval_service,
            catalog=catalog,
            modality_order=d.get("modality_order"),
            language=d.get("language", ""),
            session_cap_minutes=d.get("session_cap_minutes", DEFAULT_SESSION_CAP_MINUTES),
        )
        d["candidate_sets"] = candidate_sets
        return {"data": d}

    async def plan_draft_node(state: RunState) -> dict[str, Any]:
        d = dict(state["data"])
        counters = dict(state.get("counters") or {})
        counters["planner_attempts"] = counters.get("planner_attempts", 0) + 1

        result = await planner_agent.run(
            state["run_id"],
            {
                "candidate_sets": d["candidate_sets"],
                "hours_budget_minutes": d["hours_budget_minutes"],
                "mode": d.get("mode", "draft"),
                "existing_items": d.get("existing_items"),
                "operators": d.get("operators"),
                "validation_feedback": d.get("last_violation_messages"),
            },
        )
        d["draft_plan_items_raw"] = result["plan_items"]
        d["draft_overall_reason"] = result["overall_reason"]
        d["draft_degraded"] = result["degraded"]
        return {"data": d, "counters": counters}

    async def validate_plan_node(state: RunState) -> dict[str, Any]:
        d = dict(state["data"])
        items = _drafts_to_plan_items(d["draft_plan_items_raw"])
        gap_result: GapAnalysisResult = d["gap_result"]
        gaps_by_skill = {g.skill_id: g for g in gap_result.gaps}
        hard_prereqs_by_skill = {
            s: graph_service.direct_prerequisites(s, include_soft=False) for s in gaps_by_skill
        }
        result = validate_plan(
            items,
            candidate_sets=d["candidate_sets"],
            gaps_by_skill=gaps_by_skill,
            hard_prereqs_by_skill=hard_prereqs_by_skill,
            hours_budget_minutes=d["hours_budget_minutes"],
            new_skill_cap=d.get("new_skill_cap", NEW_SKILL_CONCURRENCY_CAP),
        )
        d["validation"] = result
        d["last_violation_messages"] = [v.message for v in result.hard_violations]

        status = "running"
        if result.passed and not d["draft_degraded"]:
            d["final_items"] = items
            d["final_overall_reason"] = d["draft_overall_reason"]
            d["final_degraded"] = False
            status = "completed"
        return {"data": d, "status": status}

    def route_after_validate(state: RunState) -> str:
        d = state["data"]
        if d["draft_degraded"]:
            return "fallback_plan"  # LLM unavailable -- deterministic, won't change on retry
        if d["validation"].passed:
            return "end"
        if state["counters"].get("planner_attempts", 0) < PLANNER_MAX_DRAFT_ATTEMPTS:
            return "plan_draft"
        return "fallback_plan"

    async def fallback_plan_node(state: RunState) -> dict[str, Any]:
        d = dict(state["data"])
        gap_result: GapAnalysisResult = d["gap_result"]
        gaps_by_skill = {g.skill_id: g for g in gap_result.gaps}
        items = build_fallback_plan(
            d["candidate_sets"],
            gaps_by_skill=gaps_by_skill,
            hours_budget_minutes=d["hours_budget_minutes"],
            new_skill_cap=d.get("new_skill_cap", NEW_SKILL_CONCURRENCY_CAP),
        )
        d["final_items"] = items
        d["final_overall_reason"] = FALLBACK_OVERALL_REASON
        d["final_degraded"] = True
        return {"data": d, "status": "completed"}

    graph = StateGraph(RunState)
    graph.add_node("build_objectives", build_objectives_node)
    graph.add_node("retrieve_candidates", retrieve_candidates_node)
    graph.add_node("plan_draft", plan_draft_node)
    graph.add_node("validate_plan", validate_plan_node)
    graph.add_node("fallback_plan", fallback_plan_node)
    graph.set_entry_point("build_objectives")
    graph.add_edge("build_objectives", "retrieve_candidates")
    graph.add_edge("retrieve_candidates", "plan_draft")
    graph.add_edge("plan_draft", "validate_plan")
    graph.add_conditional_edges(
        "validate_plan",
        route_after_validate,
        {"plan_draft": "plan_draft", "fallback_plan": "fallback_plan", "end": END},
    )
    graph.add_edge("fallback_plan", END)
    return graph.compile()


def build_evidence_response_graph():
    """G3 Evidence-Response -- design §9.5 describes this as one LangGraph
    (`record_evidence -> grade -> update_mastery -> detect_struggle -> route
    -> reflect -> validate_reflection -> patch -> commit`). This project
    built that whole pipeline instead as plain async orchestration across
    two modules -- `app/assessment/service.py` (record_evidence through
    route) and `app/reflection/service.py` (reflect through commit) -- the
    same choice Phase 8 already made for the first half of this pipeline,
    for the same reason: each step needs a DB write interleaved with the
    next step's read (mastery update before struggle classification can read
    it; a materialized probe session before `ADD_PROBE` can reference real
    item IDs), and no Postgres-backed LangGraph checkpointer exists to pause
    a graph mid-run for that (see IMPLEMENTATION_STATE.md "Known Issues").
    `app/reflection/service.py::run_reflection`'s own bounded
    agent-round-then-deterministic-fallback ladder plays the role design's
    `reflect -> validate_reflection -> [retry] -> deterministic patch` nodes
    would have. This function stays a placeholder -- no code path calls it.
    """
    raise NotImplementedError(
        "G3 Evidence-Response is implemented as plain async orchestration, not a LangGraph -- "
        "see app/assessment/service.py::submit_practice_set and app/reflection/service.py::run_reflection."
    )


def build_tutor_graph(*, ctx: TutorContext, tutor_agent: TutorAgent):
    """G4 Tutor (design §9.6): `classify_intent -> plan_tools -> call_tools
    (<= TUTOR_MAX_TOOL_STEPS) -> compose_answer -> verify_citations ->
    [regenerate once] -> stream`.

    Unlike G3 Evidence-Response, this graph has no interleaved DB *writes* to
    force plain async orchestration instead (ARCHITECTURE_CONTRACTS.md §18's
    reasoning for G3 doesn't apply here) -- every tool call and the agent
    call are pure reads, so this is a real, bounded LangGraph state machine,
    same as G1/G2.

    `classify_intent`/`plan_tools` are rule-based, not LLM-driven (design
    §9.6 allows either; see `app/tutor/intent.py`'s module docstring for why
    this project picks rule-based) -- the only LLM call in this graph is
    `compose_answer`. `ctx`/`tutor_agent` are built once per chat turn by
    `app/tutor/service.py::run_chat`, the same per-request-closure shape
    `build_planning_graph` already uses for `graph_service`/`catalog`/
    `retrieval_service`.

    Expects `state["data"]` to already contain: `message`, and optionally
    `skill_id_hint`/`decision_id_hint` (a UI "Why?" drawer already knows the
    ID it's asking about, design §24.3). Terminates with `status="completed"`
    and `state["data"]["final_answer"]`/`"final_citations"`/`"final_degraded"`/
    `"conservative"` populated either way -- a chat turn can never fail to
    produce *some* grounded answer.
    """

    async def classify_intent_node(state: RunState) -> dict[str, Any]:
        d = dict(state["data"])
        intent = await classify_intent(
            ctx, d["message"], skill_id_hint=d.get("skill_id_hint"), decision_id_hint=d.get("decision_id_hint")
        )
        d["intent"] = intent
        return {"data": d, "status": "running"}

    async def plan_tools_node(state: RunState) -> dict[str, Any]:
        d = dict(state["data"])
        d["tool_calls"] = plan_tools(d["intent"])
        return {"data": d}

    def route_after_plan_tools(state: RunState) -> str:
        d = state["data"]
        if d["intent"].name == OUT_OF_SCOPE or not d["tool_calls"]:
            return "refuse"
        return "call_tools"

    async def refuse_node(state: RunState) -> dict[str, Any]:
        d = dict(state["data"])
        d["final_answer"] = (
            "I can only answer questions about your own learning journey -- your skills, gaps, plan, "
            "or progress. Could you rephrase your question around one of those?"
        )
        d["final_citations"] = []
        d["final_degraded"] = False
        d["conservative"] = False
        return {"data": d, "status": "completed"}

    async def call_tools_node(state: RunState) -> dict[str, Any]:
        d = dict(state["data"])
        results: list[ToolCallResult] = []
        for call in d["tool_calls"]:
            results.append(await call_tool(ctx, call.tool, call.args))
        d["tool_results"] = results
        d["valid_ids"] = {cid for r in results for cid in r.citable_ids}
        return {"data": d}

    async def compose_answer_node(state: RunState) -> dict[str, Any]:
        d = dict(state["data"])
        counters = dict(state.get("counters") or {})
        counters["tool_steps"] = len(d["tool_calls"])
        compose_attempts = counters.get("compose_attempts", 0) + 1
        counters["compose_attempts"] = compose_attempts

        context_blocks = {r.tool: r.data for r in d["tool_results"] if r.data}
        result = await tutor_agent.run(
            state["run_id"],
            {
                "question": d["message"],
                "context_blocks": context_blocks,
                "missing_ids": d.get("last_invalid_citations"),
            },
        )
        d["draft"] = result["draft"]
        d["agent_degraded"] = result["degraded"]
        return {"data": d, "counters": counters}

    async def verify_citations_node(state: RunState) -> dict[str, Any]:
        d = dict(state["data"])
        if d["agent_degraded"] or d["draft"] is None:
            d["citation_check_passed"] = False
            d["last_invalid_citations"] = []
            return {"data": d}
        check = verify_citations(d["draft"].citations, d["valid_ids"])
        d["citation_check_passed"] = check.passed
        d["last_invalid_citations"] = check.invalid_ids
        return {"data": d}

    def route_after_verify(state: RunState) -> str:
        d = state["data"]
        if d["citation_check_passed"]:
            return "end"
        if d["agent_degraded"]:
            return "conservative_answer"  # LLM unavailable -- won't change on retry
        if state["counters"].get("compose_attempts", 0) < TUTOR_MAX_COMPOSE_ATTEMPTS:
            return "compose_answer"
        return "conservative_answer"

    async def finalize_verified_node(state: RunState) -> dict[str, Any]:
        d = dict(state["data"])
        d["final_answer"] = d["draft"].answer
        d["final_citations"] = d["draft"].citations
        d["final_degraded"] = False
        d["conservative"] = False
        return {"data": d, "status": "completed"}

    async def conservative_answer_node(state: RunState) -> dict[str, Any]:
        d = dict(state["data"])
        answer, citations = build_conservative_answer(d["tool_results"])
        d["final_answer"] = answer
        d["final_citations"] = citations
        d["final_degraded"] = True
        d["conservative"] = True
        return {"data": d, "status": "completed"}

    graph = StateGraph(RunState)
    graph.add_node("classify_intent", classify_intent_node)
    graph.add_node("plan_tools", plan_tools_node)
    graph.add_node("refuse", refuse_node)
    graph.add_node("call_tools", call_tools_node)
    graph.add_node("compose_answer", compose_answer_node)
    graph.add_node("verify_citations", verify_citations_node)
    graph.add_node("finalize_verified", finalize_verified_node)
    graph.add_node("conservative_answer", conservative_answer_node)
    graph.set_entry_point("classify_intent")
    graph.add_edge("classify_intent", "plan_tools")
    graph.add_conditional_edges("plan_tools", route_after_plan_tools, {"refuse": "refuse", "call_tools": "call_tools"})
    graph.add_edge("refuse", END)
    graph.add_edge("call_tools", "compose_answer")
    graph.add_edge("compose_answer", "verify_citations")
    graph.add_conditional_edges(
        "verify_citations",
        route_after_verify,
        {"end": "finalize_verified", "compose_answer": "compose_answer", "conservative_answer": "conservative_answer"},
    )
    graph.add_edge("finalize_verified", END)
    graph.add_edge("conservative_answer", END)
    return graph.compile()
