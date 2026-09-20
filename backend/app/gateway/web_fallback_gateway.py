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

import httpx

from pydantic import BaseModel, Field

from app.config import get_settings


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


# Curated learning sites a suggestion may come from (Tavily's `include_domains`). Override with
# WEB_SEARCH_ALLOWED_DOMAINS (comma-separated). design section 29: "allowlist, sanitized excerpts, unvetted badge".
DEFAULT_ALLOWED_DOMAINS = (
    "khanacademy.org", "developer.mozilla.org", "docs.python.org", "pytorch.org", "scikit-learn.org",
    "coursera.org", "edx.org", "freecodecamp.org", "kaggle.com", "huggingface.co", "realpython.com",
    "3blue1brown.com", "cs231n.github.io", "postgresql.org", "docs.docker.com", "owasp.org", "w3schools.com",
    "geeksforgeeks.org", "wikipedia.org", "mit.edu", "stanford.edu", "fast.ai", "tensorflow.org", "numpy.org", "pandas.pydata.org",
)


def _is_allowed(url: str, allowed: tuple[str, ...]) -> bool:
    from urllib.parse import urlparse

    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and any(host == d or host.endswith("." + d) for d in allowed)


class TavilyWebFallbackGateway(WebFallbackGateway):
    """Live web search (`WEB_SEARCH_PROVIDER=tavily`, needs `TAVILY_API_KEY`). Every result is
    (1) restricted to an https allowlisted domain (Tavily is asked to include only those, and the
    response is re-checked here -- a provider is not trusted to honour a filter), (2) title-only
    (page content is never passed on, so nothing in it can act as an instruction), and (3) stamped
    `unvetted`. Nothing here can put a URL into a plan or the catalog."""

    URL = "https://api.tavily.com/search"

    def __init__(self, *, api_key: str, allowed_domains: tuple[str, ...], max_results: int = 5, timeout_s: float = 20.0, client: httpx.AsyncClient | None = None) -> None:
        self._api_key, self._allowed = api_key, allowed_domains
        self._max_results, self._timeout_s, self._client = max_results, timeout_s, client

    async def search(self, query: WebFallbackQuery) -> WebFallbackResponse:
        body = {
            "query": f"{query.skill_label} tutorial course {query.query_text}".strip()[:300],
            "max_results": self._max_results,
            "search_depth": "basic",
            "include_domains": list(self._allowed),
            "include_answer": False,
            "include_raw_content": False,
        }
        try:
            http = self._client or httpx.AsyncClient(timeout=self._timeout_s)
            try:
                resp = await http.post(self.URL, json=body, headers={"Authorization": f"Bearer {self._api_key}"})
            finally:
                if self._client is None:
                    await http.aclose()
        except httpx.HTTPError as exc:
            return WebFallbackResponse(results=[], fetched=False, degraded_reason=f"network error: {type(exc).__name__}")
        if resp.status_code != 200:
            return WebFallbackResponse(results=[], fetched=False, degraded_reason=f"search provider returned {resp.status_code}")
        try:
            raw = resp.json().get("results", [])
        except ValueError:
            return WebFallbackResponse(results=[], fetched=False, degraded_reason="unparseable search response")
        results, seen = [], set()
        for item in raw:
            url = str(item.get("url", ""))
            if url in seen or not _is_allowed(url, self._allowed):
                continue
            seen.add(url)
            results.append(WebFallbackResult(url=url, title=" ".join(str(item.get("title", "")).split())[:200] or url))
        return WebFallbackResponse(results=results, fetched=True)


def get_web_fallback_gateway() -> WebFallbackGateway:
    """`WEB_SEARCH_PROVIDER=tavily` (and a `TAVILY_API_KEY`) -> live search; anything else -> degraded."""
    settings = get_settings()
    if settings.web_search_provider == "tavily" and settings.tavily_api_key:
        configured = tuple(d.strip().lower() for d in settings.web_search_allowed_domains.split(",") if d.strip())
        return TavilyWebFallbackGateway(api_key=settings.tavily_api_key, allowed_domains=configured or DEFAULT_ALLOWED_DOMAINS)
    return DegradedWebFallbackGateway()
