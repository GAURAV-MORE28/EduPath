"""G1 Onboarding orchestration glue. Builds the per-run deterministic
services from the current catalog (`CatalogRepository`), compiles and
invokes the G1 graph (`app/orchestration/graphs.py`), and persists its
`normalize_skills` output as `PendingClaim` rows — see
`build_onboarding_graph`'s docstring for why persistence (not an in-graph
pause) is how this hands off to the confirm-claims API route.
"""
from __future__ import annotations

import base64
import hashlib
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.profiler import ProfilerAgent
from app.db.models import PendingClaim
from app.gateway.embedding_gateway import EmbeddingGateway
from app.gateway.llm_gateway import LLMGateway
from app.gateway.vlm_gateway import VLMGateway
from app.orchestration.graphs import build_onboarding_graph
from app.orchestration.state import RunState
from app.profiling.claim_extraction import DeterministicClaimExtractor, SkillPhrase
from app.profiling.evidence_verifier import EvidenceVerifier
from app.profiling.skill_normalizer import SkillNormalizer
from app.repositories.catalog_repository import CatalogRepository
from app.repositories.profiling_repository import ProfilingRepository
from app.schemas.profiling import RunClaimsSummary


async def _build_fallback_extractor(catalog: CatalogRepository) -> DeterministicClaimExtractor:
    skills = await catalog.get_all_skills()
    phrases: list[SkillPhrase] = []
    for s in skills:
        phrases.append(SkillPhrase(phrase=s.label, skill_id=s.skill_id, area=s.area))
        for alias in s.aliases:
            phrases.append(SkillPhrase(phrase=alias, skill_id=s.skill_id, area=s.area))
    return DeterministicClaimExtractor(phrases)


async def run_document_onboarding(
    *,
    session: AsyncSession,
    learner_id: str,
    document_id: str,
    doc_type: str,
    raw_content: bytes | None = None,
    github_summary_text: str | None = None,
    is_github_source: bool = False,
    llm_gateway: LLMGateway,
    embedding_gateway: EmbeddingGateway,
    vlm_gateway: VLMGateway,
) -> tuple[RunClaimsSummary, str, str]:
    """Runs G1 for exactly one document (or one GitHub-derived pseudo
    document). Returns `(claims_summary, parse_status, text_hash)`. Adds `PendingClaim`
    rows to `session` (flushed, not committed — the caller owns the
    transaction boundary, matching this project's existing repository
    convention, e.g. `CatalogRepository.replace_all`).
    """
    catalog = CatalogRepository(session)
    skills = await catalog.get_all_skills()
    fallback_extractor = await _build_fallback_extractor(catalog)

    profiler_agent = ProfilerAgent(llm_gateway, fallback_extractor)
    evidence_verifier = EvidenceVerifier()
    skill_normalizer = SkillNormalizer(skills, embedding_gateway, llm_gateway)

    graph = build_onboarding_graph(
        profiler_agent=profiler_agent,
        evidence_verifier=evidence_verifier,
        skill_normalizer=skill_normalizer,
        vlm_gateway=vlm_gateway,
    )

    run_id = str(uuid.uuid4())
    initial_state: RunState = {
        "run_id": run_id,
        "learner_id": learner_id,
        "graph": "G1_onboarding",
        "status": "running",
        "counters": {},
        "data": {
            "learner_id": learner_id,
            "document_id": document_id,
            "doc_type": doc_type,
            "raw_content_b64": base64.b64encode(raw_content).decode("ascii") if raw_content is not None else None,
            "github_summary_text": github_summary_text,
            "is_github_source": is_github_source,
        },
    }

    final_state = await graph.ainvoke(initial_state)
    d = final_state["data"]

    normalized = d.get("normalized_claims", [])
    pending_rows = [
        PendingClaim(
            learner_id=learner_id,
            run_id=run_id,
            document_id=document_id,
            skill_label=n["verified"]["claim"]["label"],
            category=n["verified"]["claim"]["category"],
            context_type=n["verified"]["claim"]["context_type"],
            claimed_level_cue=n["verified"]["claim"]["claimed_level_cue"],
            verbatim_span=n["verified"]["claim"]["verbatim_span"],
            span_offsets=n["verified"]["claim"]["span_offsets"],
            tier=n["verified"]["tier"],
            normalized_skill_id=n["skill_id"],
            normalization_method=n["method"],
            normalization_confidence=n["confidence"],
        )
        for n in normalized
    ]
    if pending_rows:
        await ProfilingRepository(session).create_pending_claims(pending_rows)

    summary = RunClaimsSummary(
        run_id=run_id,
        extracted=len(d.get("claims_raw", [])),
        dropped_unverified=d.get("dropped_unverified", 0),
        dropped_injection=d.get("dropped_injection", 0),
        pending=len(pending_rows),
        degraded=d.get("extraction_degraded", False),
    )
    text_hash = hashlib.sha256(d.get("source_text", "").encode("utf-8")).hexdigest()
    return summary, d.get("parse_status", "parsed"), text_hash
