"""Live LLM provider adapter(s) behind the gateway (design §7, §33.2).

Two adapters exist, both over plain `httpx` (no SDKs): Anthropic's Messages API,
and the OpenAI chat-completions dialect that Groq and the Hugging Face router
both speak (`call_openai_compatible`). It is deliberately thin: it sends the system/user
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

    def __init__(self, message: str, *, retryable: bool = True, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.retry_after = retry_after  # seconds, from a 429's Retry-After header when the provider sends one


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
        response = await http.post(f"{(settings.llm_base_url or 'https://api.anthropic.com').rstrip('/')}/v1/messages", json=payload, headers=headers)
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


OPENAI_COMPATIBLE_DEFAULTS = {
    "groq": ("https://api.groq.com/openai/v1", "llm_api_key"),
    "huggingface": ("https://router.huggingface.co/v1", "hf_token"),
}


def _retry_after(response: httpx.Response) -> float | None:
    try:
        return float(response.headers.get("retry-after", ""))
    except ValueError:
        return None


async def call_openai_compatible(
    settings: Settings,
    *,
    provider: str,
    tier: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float,
    client: httpx.AsyncClient | None = None,
) -> ProviderResult:
    """Chat completion against Groq (`LLM_PROVIDER=groq`) or the Hugging Face router
    (`LLM_PROVIDER=huggingface`). Asks for a JSON object (`llm_json_mode`) because every agent's
    contract is schema-only JSON; if the provider rejects that parameter, it is retried once without it.
    Reasoning models spend tokens thinking: `reasoning_effort` is sent only to gpt-oss models."""
    default_url, key_field = OPENAI_COMPATIBLE_DEFAULTS[provider]
    api_key = getattr(settings, key_field) or settings.llm_api_key or settings.hf_token
    model = model_for_tier(settings, tier)
    if not model or not api_key:
        raise ProviderError(f"no model/API key configured for tier '{tier}' (provider {provider})", retryable=False)

    body: dict = {
        "model": model,
        "temperature": temperature,
        "max_tokens": 4096,
        "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
    }
    if "gpt-oss" in model and settings.llm_reasoning_effort:
        body["reasoning_effort"] = settings.llm_reasoning_effort
    headers = {"Authorization": f"Bearer {api_key}", "content-type": "application/json"}
    url = f"{(settings.llm_base_url or default_url).rstrip('/')}/chat/completions"

    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=settings.llm_timeout_s)
    try:
        attempts = [True, False] if settings.llm_json_mode else [False]
        for use_json_mode in attempts:
            payload = dict(body)
            if use_json_mode:
                payload["response_format"] = {"type": "json_object"}
            try:
                response = await http.post(url, json=payload, headers=headers)
            except httpx.HTTPError as exc:
                raise ProviderError(f"transport error: {type(exc).__name__}") from exc
            if response.status_code == 400 and use_json_mode and "json" in response.text.lower():
                continue  # this model/prompt does not support JSON mode: retry once as plain text
            break
    finally:
        if owns_client:
            await http.aclose()

    if response.status_code == 429 or response.status_code >= 500:
        raise ProviderError(f"provider returned {response.status_code}", retry_after=_retry_after(response))
    if response.status_code >= 400:
        raise ProviderError(f"provider rejected the request ({response.status_code}): {response.text[:160]}", retryable=False)
    try:
        data = response.json()
        message = data["choices"][0]["message"]
        text = message.get("content") or ""
        usage = data.get("usage") or {}
    except (ValueError, KeyError, IndexError, AttributeError, TypeError) as exc:
        raise ProviderError("unparseable provider response") from exc
    if not text:
        raise ProviderError("empty provider response")
    return ProviderResult(
        text=text,
        tokens_in=int(usage.get("prompt_tokens", 0) or 0),
        tokens_out=int(usage.get("completion_tokens", 0) or 0),
        model=str(data.get("model") or model),
    )
