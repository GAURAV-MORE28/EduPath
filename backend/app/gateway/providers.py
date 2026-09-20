"""Live LLM provider adapter(s) behind the gateway (design §7, §33.2).

Only one adapter exists: Anthropic's Messages API over plain `httpx` (already
a dependency -- no SDK). It is deliberately thin: it sends the system/user
prompt for the requested tier's configured model and returns raw text plus
token usage. JSON extraction and schema validation stay where they always
were (each agent's `parse_*` + retry loop), so a malformed answer is retried
by the agent, never trusted.

Nothing here raises to callers: every failure mode becomes a `ProviderError`
that `LLMGateway.complete` turns into backoff -> replay -> deterministic
degradation (ARCHITECTURE_CONTRACTS.md §11).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

import httpx

from app.config import Settings


class ProviderError(Exception):
    """Timeout / transport error / 5xx / 429 / unusable response."""

    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


@dataclass
class ProviderResult:
    text: str
    tokens_in: int = 0
    tokens_out: int = 0
    model: str = ""


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def extract_json_object(text: str) -> dict | None:
    """Best-effort parse of a model answer into a JSON object (fenced or bare).
    Returns None when there isn't one -- the agent's own validation then retries."""
    candidate = _FENCE.sub("", text.strip())
    for attempt in (candidate, candidate[candidate.find("{") : candidate.rfind("}") + 1] if "{" in candidate else ""):
        if not attempt:
            continue
        try:
            value = json.loads(attempt)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(value, dict):
            return value
    return None


def model_for_tier(settings: Settings, tier: str) -> str:
    return {"small": settings.llm_small_model, "mid": settings.llm_mid_model, "strong": settings.llm_strong_model}.get(tier, "")


async def call_anthropic(
    settings: Settings,
    *,
    tier: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float,
    client: httpx.AsyncClient | None = None,
) -> ProviderResult:
    model = model_for_tier(settings, tier)
    if not model or not settings.llm_api_key:
        raise ProviderError(f"no model/API key configured for tier '{tier}'", retryable=False)

    payload = {
        "model": model,
        "max_tokens": 4096,
        "temperature": temperature,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_prompt}],
    }
    headers = {"x-api-key": settings.llm_api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=settings.llm_timeout_s)
    try:
        response = await http.post(f"{settings.llm_base_url.rstrip('/')}/v1/messages", json=payload, headers=headers)
    except httpx.HTTPError as exc:  # timeout, connect error, ...
        raise ProviderError(f"transport error: {type(exc).__name__}") from exc
    finally:
        if owns_client:
            await http.aclose()

    if response.status_code == 429 or response.status_code >= 500:
        raise ProviderError(f"provider returned {response.status_code}")
    if response.status_code >= 400:
        raise ProviderError(f"provider rejected the request ({response.status_code})", retryable=False)

    try:
        body = response.json()
        text = "".join(block.get("text", "") for block in body.get("content", []) if block.get("type") == "text")
        usage = body.get("usage") or {}
    except (ValueError, AttributeError) as exc:
        raise ProviderError("unparseable provider response") from exc
    if not text:
        raise ProviderError("empty provider response")
    return ProviderResult(
        text=text,
        tokens_in=int(usage.get("input_tokens", 0) or 0),
        tokens_out=int(usage.get("output_tokens", 0) or 0),
        model=model,
    )
