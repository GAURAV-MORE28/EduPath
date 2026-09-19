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

from app.agents.profiler import ProfilerAgent
from app.gateway.vlm_gateway import VLMGateway, VLMPageReadRequest
from app.orchestration.state import RunState
from app.profiling.document_parser import extract_text
from app.profiling.evidence_verifier import EvidenceVerifier
from app.profiling.pii import scrub_pii
from app.profiling.skill_normalizer import SkillNormalizer
from app.schemas.profiling import ExtractedClaim, VerifiedClaim


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


def build_planning_graph():
    """G2 Planning — placeholder. Implemented in Phase 5."""
    raise NotImplementedError("G2 Planning graph is implemented in Phase 5 (Planner).")


def build_evidence_response_graph():
    """G3 Evidence-Response — placeholder. Implemented in Phase 8."""
    raise NotImplementedError("G3 Evidence-Response graph is implemented in Phase 8 (Reflection / re-planning).")


def build_tutor_graph():
    """G4 Tutor — placeholder. Implemented in Phase 9."""
    raise NotImplementedError("G4 Tutor graph is implemented in Phase 9 (Tutor).")
