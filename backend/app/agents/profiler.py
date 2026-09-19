"""Profiler Agent (A1) — design §8.2, §22. Converts a (scrubbed, PII-free)
document text into `ExtractedClaim`s. No side-effect tools; output is
schema-only; the LLM's evidence span is never trusted blindly — span
verification happens downstream, in the Evidence Verifier
(`app/profiling/evidence_verifier.py`), not here.

Two code paths, tried in order per run:
1. Real LLM extraction (mid/strong tier, design §33.2), retried up to 2x on
   schema-validation failure (ARCHITECTURE_CONTRACTS.md §11).
2. Deterministic fallback (`DeterministicClaimExtractor`) when the gateway
   degrades (no provider configured -- this project's default) or both
   retries fail. This is what the test suite exercises: `LLM_PROVIDER=none`
   in tests (see `tests/conftest.py`), by design, so claim generation stays
   fully offline-testable.
"""
from __future__ import annotations

from typing import Any

from app.agents.base import Agent
from app.gateway.llm_gateway import LLMGateway, LLMRequest, ModelTier
from app.profiling.claim_extraction import (
    EXTRACTION_SYSTEM_PROMPT,
    DeterministicClaimExtractor,
    ExtractionParseError,
    build_extraction_prompt,
    parse_extraction_response,
)
from app.schemas.profiling import ExtractedClaim


class ProfilerAgent(Agent):
    name = "profiler"
    max_retries = 2  # ARCHITECTURE_CONTRACTS.md §11: schema-validation failure -> retry, max 2 times

    def __init__(self, gateway: LLMGateway, fallback_extractor: DeterministicClaimExtractor) -> None:
        super().__init__(gateway)
        self.fallback_extractor = fallback_extractor

    async def run(self, run_id: str, input_payload: dict[str, Any]) -> dict[str, Any]:
        document_text: str = input_payload["document_text"]
        source_doc_id: str = input_payload["source_doc_id"]

        claims, degraded = await self._extract_via_llm(document_text, source_doc_id)
        if claims is None:
            claims = self.fallback_extractor.extract(document_text, source_doc_id)
            degraded = True

        return {"claims": [c.model_dump(mode="json") for c in claims], "degraded": degraded}

    async def _extract_via_llm(
        self, document_text: str, source_doc_id: str
    ) -> tuple[list[ExtractedClaim] | None, bool]:
        base_prompt = build_extraction_prompt(document_text, source_doc_id)
        last_error: str | None = None

        for attempt in range(self.max_retries + 1):
            user_prompt = (
                base_prompt
                if last_error is None
                else f"{base_prompt}\n\nYour previous response was invalid: {last_error}\n"
                "Output ONLY the corrected JSON array."
            )
            response = await self.gateway.complete(
                LLMRequest(
                    tier=ModelTier.MID,  # design §33.2: document extraction is a mid/strong-tier task
                    system_prompt=EXTRACTION_SYSTEM_PROMPT,
                    user_prompt=user_prompt,
                    schema_name="ExtractedClaims",
                    temperature=0.0,
                )
            )
            if response.degraded:
                return None, True
            try:
                return parse_extraction_response(response.raw_text, source_doc_id), False
            except ExtractionParseError as exc:
                last_error = str(exc)
                continue

        return None, True
