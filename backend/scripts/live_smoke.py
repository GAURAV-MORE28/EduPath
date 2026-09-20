"""Live smoke test of every external service, through the project's own gateways.

    cd backend && python scripts/live_smoke.py

Reads `backend/.env` (LLM_PROVIDER / EMBEDDING_PROVIDER / VLM_PROVIDER / WEB_SEARCH_PROVIDER, keys,
model ids). Makes a handful of tiny real calls and prints PASS / FAIL / SKIP per service -- no secrets are
printed. Exit code 0 iff nothing that is *configured* failed. This is what `docker compose` cannot tell you:
whether the keys and model ids you configured actually work.
"""
from __future__ import annotations

import asyncio
import base64
import sys
import time

import httpx

from app.config import get_settings
from app.gateway.embedding_gateway import HuggingFaceEmbeddingGateway, get_embedding_gateway
from app.gateway.llm_gateway import InMemoryReplayCache, LLMGateway, LLMRequest, ModelTier
from app.gateway.vlm_gateway import VLMPageReadRequest, get_vlm_gateway
from app.gateway.web_fallback_gateway import WebFallbackQuery, get_web_fallback_gateway
from app.profiling.github_client import GitHubClient

results: list[tuple[str, str, str]] = []


def report(name: str, status: str, detail: str = "") -> None:
    results.append((name, status, detail))
    print(f"{status:<5} {name:<34} {detail}")


async def check_llm() -> None:
    s = get_settings()
    if s.llm_provider == "none":
        return report("llm", "SKIP", "LLM_PROVIDER=none")
    for tier in ModelTier:
        started = time.perf_counter()
        gateway = LLMGateway(cache=InMemoryReplayCache())
        resp = await gateway.complete(
            LLMRequest(tier=tier, system_prompt="You reply with a single JSON object only.", user_prompt='Return {"answer": 4} for 2+2. Respond in JSON.', schema_name="LiveSmoke")
        )
        ok = not resp.degraded and isinstance(resp.parsed, dict) and resp.parsed.get("answer") == 4
        report(f"llm[{tier.value}]", "PASS" if ok else "FAIL", f"{resp.model or getattr(s, f'llm_{tier.value}_model')} {(time.perf_counter() - started) * 1000:.0f} ms, {resp.tokens_in}+{resp.tokens_out} tokens" + (f" ({resp.error})" if resp.error else ""))


async def check_embeddings() -> None:
    s = get_settings()
    gw = get_embedding_gateway()
    if not isinstance(gw, HuggingFaceEmbeddingGateway):
        return report("embeddings", "SKIP", f"EMBEDDING_PROVIDER={s.embedding_provider}")
    started = time.perf_counter()
    vecs = await gw.embed_many(["chain rule", "backpropagation", "differentiating composite functions"])
    real = "chain rule" in gw._cache
    cos = lambda a, b: sum(x * y for x, y in zip(a, b))  # noqa: E731 -- vectors are unit-length
    related, unrelated = cos(vecs[0], vecs[2]), cos(vecs[0], (await gw.embed("Italian pasta recipes")))
    ok = real and len(vecs[0]) == 256 and related > unrelated
    report("embeddings", "PASS" if ok else "FAIL", f"{s.embedding_model} dim={len(vecs[0])} related={related:.2f} vs unrelated={unrelated:.2f} {(time.perf_counter() - started) * 1000:.0f} ms" + ("" if real else " (FELL BACK to deterministic)"))


async def check_vlm() -> None:
    s = get_settings()
    gw = get_vlm_gateway()
    if s.vlm_provider != "huggingface":
        return report("vlm", "SKIP", f"VLM_PROVIDER={s.vlm_provider}")
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), "Asha Rao - Resume", fontsize=20)
    page.insert_text((72, 140), "Skills: Python, PyTorch, OpenCV", fontsize=14)
    png = page.get_pixmap(dpi=110).tobytes("png")
    started = time.perf_counter()
    resp = await gw.read_page(VLMPageReadRequest(document_id="smoke", image_bytes_b64=base64.b64encode(png).decode()))
    ok = not resp.degraded and "pytorch" in resp.text.lower()
    report("vlm", "PASS" if ok else "FAIL", f"{s.vlm_model} {(time.perf_counter() - started) * 1000:.0f} ms, read: {resp.text[:60]!r}" + (" (degraded)" if resp.degraded else ""))


async def check_web() -> None:
    s = get_settings()
    gw = get_web_fallback_gateway()
    if s.web_search_provider != "tavily":
        return report("web search", "SKIP", f"WEB_SEARCH_PROVIDER={s.web_search_provider}")
    resp = await gw.search(WebFallbackQuery(skill_label="Chain Rule", query_text="calculus"))
    ok = resp.fetched and bool(resp.results) and all(r.curation_tier == "unvetted" and r.url.startswith("https://") for r in resp.results)
    report("web search", "PASS" if ok else "FAIL", f"{len(resp.results)} allowlisted, unvetted results" + (f" ({resp.degraded_reason})" if resp.degraded_reason else ""))


async def check_github() -> None:
    s = get_settings()
    if not s.github_token:
        return report("github", "SKIP", "no GITHUB_TOKEN (unauthenticated: 60 requests/hour)")
    async with httpx.AsyncClient(timeout=20) as http:
        summary = await GitHubClient(http).repo_summary("https://github.com/psf/requests")
        rate = await http.get("https://api.github.com/rate_limit", headers={"Authorization": f"Bearer {s.github_token}"})
    limit = rate.json()["resources"]["core"]["limit"] if rate.status_code == 200 else "?"
    report("github", "PASS" if summary.fetched and "Python" in summary.languages else "FAIL", f"psf/requests fetched={summary.fetched}, authenticated rate limit {limit}/h")


async def main() -> int:
    s = get_settings()
    print(f"providers: llm={s.llm_provider} embeddings={s.embedding_provider} vlm={s.vlm_provider} web={s.web_search_provider}\n")
    for check in (check_llm, check_embeddings, check_vlm, check_web, check_github):
        try:
            await check()
        except Exception as exc:  # noqa: BLE001 -- a smoke test reports, it does not crash
            report(check.__name__.removeprefix("check_"), "FAIL", f"{type(exc).__name__}: {str(exc)[:120]}")
    return 1 if any(r[1] == "FAIL" for r in results) else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
