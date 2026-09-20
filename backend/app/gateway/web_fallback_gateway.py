"""Web fallback Gateway — design §14.3 point 6 / §15.2's "O4" optional
extension: "if fewer than N eligible resources, run a web search, then
apply URL validation (HEAD request), a domain allowlist and LLM-extracted
metadata. Results are marked `unvetted` and never auto-placed in a plan
without a visible badge."

Same provider-agnostic-gateway shape as the LLM/Embedding/VLM Gateways
(degrades deterministically, `fetched=False`, when no provider is
configured — this project's permanent state, since no web-search provider
or domain allowlist has been wired in). The Resource Retriever
(`app/retrieval/service.py`) never calls this automatically; a caller must
explicitly opt in (`allow_web_fallback=True`) precisely because these
results are `unvetted` and must never silently substitute for the curated
catalog (design §15.2: "No resource may enter a plan unless its ID exists
in the catalog" — a web-fallback result is intentionally *not* in the
catalog, so it is returned separately, never merged into
`ResourceRecommendation[]` as if it were a real catalog resource).
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel, Field


UNVETTED = "unvetted"


class WebFallbackQuery(BaseModel):
    skill_label: str
    query_text: str


class WebFallbackResult(BaseModel):
    """Deliberately *not* `ResourceCandidate`/`ResourceRecommendation` --
    this has no `resource_id` (nothing in the catalog to reference), so it
    cannot be confused with a real, ID-backed recommendation
    (ARCHITECTURE_CONTRACTS.md §7: "an LLM never emits a raw URL or invents
    an ID"). A caller that wants to actually add this to a plan must first
    run it through URL validation + a domain allowlist and give it a real
    catalog entry — out of scope for this gateway."""

    url: str
    title: str
    curation_tier: str = UNVETTED


class WebFallbackResponse(BaseModel):
    results: list[WebFallbackResult] = Field(default_factory=list)
    fetched: bool = False
    degraded_reason: str | None = None


class WebFallbackGateway(ABC):
    @abstractmethod
    async def search(self, query: WebFallbackQuery) -> WebFallbackResponse: ...


class DegradedWebFallbackGateway(WebFallbackGateway):
    """Default gateway when no web-search provider is configured
    (`settings.llm_provider == "none"`). Always reports `fetched=False`
    with no results -- there is no offline stand-in for a live web search,
    so a caller with too few eligible catalog resources just gets fewer
    recommendations, never fabricated ones."""

    async def search(self, query: WebFallbackQuery) -> WebFallbackResponse:
        return WebFallbackResponse(results=[], fetched=False, degraded_reason="no web-search provider configured")


def get_web_fallback_gateway():
    """Always the deterministic/degraded gateway: no web-search provider is
    implemented in this project, so a configured `LLM_PROVIDER` (which only
    routes the LLM Gateway) must not make this raise -- Phase 12 fixed a crash
    where any provider other than "none" turned intake/upload/planning into a
    500. The degrade is reported honestly by each response's own flags."""
    return DegradedWebFallbackGateway()
