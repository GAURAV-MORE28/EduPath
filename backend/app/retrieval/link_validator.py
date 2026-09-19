"""Resource link validation (design §15.2: "Link validation job: runs before
demo and nightly. Sets `link_status`. A broken link makes a resource
ineligible."). This is the *live* check -- static URL well-formedness
(scheme/netloc sanity) is already a build-time invariant in
`app/graph/validation.py` (Phase 3), run at ingestion time; this module is
the network-dependent half design §15.1's `link_status` field needs.

`httpx.AsyncClient` is injected (same pattern as `app/profiling/github_client.py`)
so tests use `httpx.MockTransport` -- no live network calls in the test suite.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date

import httpx

LINK_STATUS_OK = "ok"
LINK_STATUS_REDIRECTED = "redirected"
LINK_STATUS_BROKEN = "broken"

DEFAULT_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class LinkCheckResult:
    resource_id: str
    url: str
    status: str  # ok | redirected | broken
    checked_at: date
    detail: str = ""  # e.g. "HTTP 404", "timeout", "connection error" -- for logging/debugging only


async def check_url(client: httpx.AsyncClient, url: str, *, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> tuple[str, str]:
    """Returns `(status, detail)`. Tries `HEAD` first (cheap); some hosts
    reject `HEAD` (405/403 without a real check), so a non-2xx/3xx `HEAD`
    result falls through to a `GET` before declaring the link broken --
    the same "don't trust one signal" caution as the Evidence Verifier's
    span-recovery search.
    """
    for method in ("HEAD", "GET"):
        try:
            resp = await client.request(method, url, follow_redirects=True, timeout=timeout)
        except httpx.HTTPError as exc:
            return LINK_STATUS_BROKEN, f"{type(exc).__name__}: {exc}"
        if resp.status_code < 400:
            return (LINK_STATUS_REDIRECTED if resp.history else LINK_STATUS_OK), f"HTTP {resp.status_code}"
        if method == "HEAD":
            continue  # try GET before giving up
        return LINK_STATUS_BROKEN, f"HTTP {resp.status_code}"
    return LINK_STATUS_BROKEN, "unreachable"  # unreachable in practice; keeps type checkers happy


async def validate_resources(
    resources: list[tuple[str, str]],  # (resource_id, url) pairs
    client: httpx.AsyncClient,
    *,
    as_of: date | None = None,
    max_concurrency: int = 10,
) -> list[LinkCheckResult]:
    """Runs `check_url` over every `(resource_id, url)` pair, bounded by
    `max_concurrency` (a curated catalog is ~140 resources -- cheap either
    way, but a live demo shouldn't fire 140 concurrent requests at once)."""
    as_of = as_of or date.today()
    semaphore = asyncio.Semaphore(max_concurrency)

    async def _one(resource_id: str, url: str) -> LinkCheckResult:
        async with semaphore:
            status, detail = await check_url(client, url)
        return LinkCheckResult(resource_id=resource_id, url=url, status=status, checked_at=as_of, detail=detail)

    return list(await asyncio.gather(*(_one(rid, url) for rid, url in resources)))
