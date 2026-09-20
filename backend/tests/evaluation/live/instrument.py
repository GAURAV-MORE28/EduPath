"""Instrumentation for the LIVE LLM evaluation (docs/LLM_EVALUATION.md).

Nothing in here mocks or replaces a provider. It *wraps* the real calls so every one of them is measured:

  * `LLMGateway.complete`        -> one `LLMCall` per gateway call (operation, tier, model, latency, tokens,
                                    degraded / replayed flags, error category)
  * `_default_provider_call`     -> per-attempt latency + error category, i.e. the gateway's own retries
  * the agents' `note_retry`     -> schema-validation retries (agent level)
  * embedding / VLM / web search -> one `ProviderCall` per remote request, incl. silent fallbacks

A "case" (`CaseContext`) is the unit the report aggregates. Each case owns the calls made while it runs
(via a ContextVar, so concurrent cases would not mix). Setup work that is not the behaviour under test can run
inside `setup_mode()`: the LLM provider is then explicitly refused (no network call) so the agents take their
deterministic path and no quota is spent -- those calls are recorded as `setup=True` and never counted.

No secret ever enters a record: errors are passed through `redact()` and only the *names* of settings are kept.
"""
from __future__ import annotations

import asyncio
import math
import re
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

# --------------------------------------------------------------------------------------------------------------------
# helpers

_TOKEN_PATTERNS = [
    re.compile(r"gsk_[A-Za-z0-9]{8,}"),
    re.compile(r"hf_[A-Za-z0-9]{8,}"),
    re.compile(r"tvly-[A-Za-z0-9\-]{6,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{8,}"),
    re.compile(r"sk-[A-Za-z0-9\-_]{8,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._\-]{8,}", re.IGNORECASE),
]
_SECRET_VALUES: set[str] = set()


def register_secrets(*values: str) -> None:
    """Remember literal secret values (from settings) so `redact` can scrub them. Never stored in a report."""
    _SECRET_VALUES.update(v for v in values if v and len(v) >= 8)


def redact(text: str, limit: int = 240) -> str:
    out = str(text)
    for secret in _SECRET_VALUES:
        out = out.replace(secret, "[REDACTED]")
    for pattern in _TOKEN_PATTERNS:
        out = pattern.sub("[REDACTED]", out)
    return out[:limit]


def percentile(values: list[float], p: float) -> float | None:
    """Nearest-rank percentile; None for an empty list (never a fabricated 0)."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, min(len(ordered) - 1, math.ceil(p / 100 * len(ordered)) - 1))]


def mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def categorize_error(message: str | None) -> str | None:
    """Map a gateway/provider error string to a coarse, secret-free category."""
    if not message:
        return None
    low = message.lower()
    if "429" in low or "rate" in low and "limit" in low:
        return "rate_limit"
    if "timeout" in low or "timed out" in low:
        return "timeout"
    if "transport error" in low or "connect" in low:
        return "transport"
    if "413" in low or "too large" in low:
        return "payload_too_large"
    if re.search(r"returned 5\d\d", low) or "5xx" in low:
        return "server_error"
    if "rejected the request" in low:
        return "client_error"
    if "empty provider response" in low:
        return "empty_response"
    if "unparseable" in low:
        return "unparseable_response"
    if "no model/api key" in low or "not configured" in low or "unsupported llm_provider" in low:
        return "not_configured"
    if "setup" in low and "disabled" in low:
        return "harness_setup_disabled"
    return "other"


TRANSIENT_CATEGORIES = {"rate_limit", "timeout", "transport", "server_error", "payload_too_large", "empty_response"}

# --------------------------------------------------------------------------------------------------------------------
# records


@dataclass
class AttemptRecord:
    latency_ms: float
    error_category: str | None = None
    retry_after_s: float | None = None  # from a 429's Retry-After: seconds => a per-minute limit, minutes => a daily quota


@dataclass
class LLMCall:
    operation: str  # the case id
    schema_name: str
    tier: str
    provider: str
    model: str = ""
    latency_ms: float = 0.0  # whole gateway call, incl. backoff between attempts
    attempts: list[AttemptRecord] = field(default_factory=list)
    degraded: bool = False
    from_replay: bool = False
    tokens_in: int = 0
    tokens_out: int = 0
    error_category: str | None = None
    non_json: bool = False  # provider answered but the text held no JSON object
    setup: bool = False

    @property
    def gateway_retries(self) -> int:
        return max(0, len(self.attempts) - 1)

    def as_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation, "schema": self.schema_name, "tier": self.tier, "provider": self.provider,
            "model": self.model, "latency_ms": round(self.latency_ms, 1), "attempts": len(self.attempts),
            "attempt_errors": [a.error_category for a in self.attempts if a.error_category],
            "retry_after_s": [a.retry_after_s for a in self.attempts if a.retry_after_s is not None],
            "degraded": self.degraded, "from_replay": self.from_replay, "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out, "error_category": self.error_category, "non_json": self.non_json,
        }


@dataclass
class ProviderCall:
    """A non-LLM remote request: embeddings / vision / web search."""

    operation: str
    provider: str  # embeddings | vlm | web_search
    model: str = ""
    latency_ms: float = 0.0
    ok: bool = True
    fell_back: bool = False  # the gateway silently substituted a deterministic answer
    error_category: str | None = None
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"operation": self.operation, "provider": self.provider, "model": self.model,
                "latency_ms": round(self.latency_ms, 1), "ok": self.ok, "fell_back": self.fell_back,
                "error_category": self.error_category, "detail": self.detail}


@dataclass
class CaseContext:
    area: str
    case_id: str
    llm_calls: list[LLMCall] = field(default_factory=list)
    provider_calls: list[ProviderCall] = field(default_factory=list)
    agent_retries: int = 0
    setup_only: bool = False  # inside setup_mode()


_current_case: ContextVar[CaseContext | None] = ContextVar("llm_eval_case", default=None)
_current_call: ContextVar[LLMCall | None] = ContextVar("llm_eval_call", default=None)
_setup_mode: ContextVar[bool] = ContextVar("llm_eval_setup", default=False)


def current_case() -> CaseContext | None:
    return _current_case.get()


@contextmanager
def case_scope(ctx: CaseContext):
    token = _current_case.set(ctx)
    try:
        yield ctx
    finally:
        _current_case.reset(token)


@contextmanager
def setup_mode():
    """Explicitly refuse the LLM provider (no network) for scaffolding that is not the behaviour under test."""
    token = _setup_mode.set(True)
    try:
        yield
    finally:
        _setup_mode.reset(token)


# --------------------------------------------------------------------------------------------------------------------
# the recorder


class Recorder:
    """Installs wrappers on the real gateways. `install()` is idempotent; `uninstall()` restores everything."""

    def __init__(self) -> None:
        self.llm_calls: list[LLMCall] = []
        self.provider_calls: list[ProviderCall] = []
        self._undo: list[tuple[Any, str, Any]] = []
        self._installed = False
        self._last_embedding_reason = ""

    # -- patch plumbing
    def _patch(self, obj: Any, name: str, value: Any) -> None:
        self._undo.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    def install(self) -> "Recorder":
        if self._installed:
            return self
        self._installed = True
        from app.gateway import embedding_gateway as emb
        from app.gateway import llm_gateway as llm
        from app.gateway import vlm_gateway as vlm
        from app.gateway import web_fallback_gateway as web
        from app.gateway.providers import ProviderError

        recorder = self
        orig_provider_call = llm._default_provider_call
        orig_complete = llm.LLMGateway.complete

        async def provider_call(settings, request):
            call = _current_call.get()
            started = time.perf_counter()
            if _setup_mode.get():
                if call is not None:
                    call.attempts.append(AttemptRecord(0.0, "harness_setup_disabled"))
                raise ProviderError("setup scaffolding: LLM provider disabled by the evaluation harness", retryable=False)
            try:
                result = await orig_provider_call(settings, request)
            except ProviderError as exc:
                if call is not None:
                    call.attempts.append(AttemptRecord((time.perf_counter() - started) * 1000, categorize_error(str(exc)) or "other", exc.retry_after))
                raise
            except asyncio.CancelledError:  # asyncio.wait_for in the gateway cancels the attempt on timeout
                if call is not None:
                    call.attempts.append(AttemptRecord((time.perf_counter() - started) * 1000, "timeout"))
                raise
            except Exception as exc:  # noqa: BLE001
                if call is not None:
                    call.attempts.append(AttemptRecord((time.perf_counter() - started) * 1000, f"unexpected:{type(exc).__name__}"))
                raise
            if call is not None:
                call.attempts.append(AttemptRecord((time.perf_counter() - started) * 1000, None))
            return result

        async def complete(self, request):
            ctx = _current_case.get()
            settings = self.settings
            call = LLMCall(
                operation=ctx.case_id if ctx else "", schema_name=request.schema_name, tier=request.tier.value,
                provider=settings.llm_provider, setup=_setup_mode.get(),
            )
            token = _current_call.set(call)
            started = time.perf_counter()
            try:
                response = await orig_complete(self, request)
            finally:
                _current_call.reset(token)
            call.latency_ms = (time.perf_counter() - started) * 1000
            call.model = response.model or ""
            call.degraded, call.from_replay = response.degraded, response.from_replay
            call.tokens_in, call.tokens_out = response.tokens_in, response.tokens_out
            call.non_json = (not response.degraded) and response.parsed is None
            if response.degraded:
                errors = [a.error_category for a in call.attempts if a.error_category]
                call.error_category = errors[-1] if errors else categorize_error(response.error) or "degraded_no_provider"
            recorder.llm_calls.append(call)
            if ctx is not None:
                ctx.llm_calls.append(call)
            return response

        self._patch(llm, "_default_provider_call", provider_call)
        self._patch(llm.LLMGateway, "complete", complete)

        # agent-level (schema validation) retries: each agent imported `note_retry` by name
        import importlib

        for module_name in ("profiler", "planner", "assessor", "reflection", "tutor"):
            module = importlib.import_module(f"app.agents.{module_name}")
            orig_note = module.note_retry

            def make(orig):
                def note_retry():
                    ctx = _current_case.get()
                    if ctx is not None and not _setup_mode.get():
                        ctx.agent_retries += 1
                    return orig()

                return note_retry

            self._patch(module, "note_retry", make(orig_note))

        # embeddings: the gateway silently falls back to a deterministic vector -- make that visible (and keep the reason)
        class _LogTap:
            def __init__(self, inner):
                self._inner = inner

            def __getattr__(self, name):
                return getattr(self._inner, name)

            def warning(self, event, *args, **kwargs):
                if event == "edupath.embedding.remote_failed_using_deterministic_fallback":
                    recorder._last_embedding_reason = str(kwargs.get("reason", ""))
                return self._inner.warning(event, *args, **kwargs)

        self._patch(emb, "logger", _LogTap(emb.logger))
        orig_request = emb.HuggingFaceEmbeddingGateway._request

        async def emb_request(self, batch):
            started = time.perf_counter()
            recorder._last_embedding_reason = ""
            vectors, real = await orig_request(self, batch)
            pc = ProviderCall("", "embeddings", model=getattr(self, "_model", ""), latency_ms=(time.perf_counter() - started) * 1000,
                              ok=real, fell_back=not real, error_category=None if real else "fell_back_to_deterministic",
                              detail=f"batch={len(batch)}" + ("" if real else f" reason={redact(recorder._last_embedding_reason, 60)}"))
            recorder._add_provider_call(pc)
            return vectors, real

        self._patch(emb.HuggingFaceEmbeddingGateway, "_request", emb_request)

        orig_read = vlm.HuggingFaceVLMGateway.read_page

        async def read_page(self, request):
            started = time.perf_counter()
            response = await orig_read(self, request)
            recorder._add_provider_call(ProviderCall(
                "", "vlm", model=getattr(self, "_model", ""), latency_ms=(time.perf_counter() - started) * 1000,
                ok=not response.degraded, fell_back=response.degraded, error_category="degraded" if response.degraded else None,
                detail=f"chars={len(response.text)}"))
            return response

        self._patch(vlm.HuggingFaceVLMGateway, "read_page", read_page)

        orig_search = web.TavilyWebFallbackGateway.search

        async def search(self, query):
            started = time.perf_counter()
            response = await orig_search(self, query)
            recorder._add_provider_call(ProviderCall(
                "", "web_search", model="tavily", latency_ms=(time.perf_counter() - started) * 1000, ok=response.fetched,
                error_category=categorize_error(response.degraded_reason) if not response.fetched else None,
                detail=f"results={len(response.results)}" + (f" reason={redact(response.degraded_reason or '', 80)}" if response.degraded_reason else "")))
            return response

        self._patch(web.TavilyWebFallbackGateway, "search", search)
        return self

    def _add_provider_call(self, pc: ProviderCall) -> None:
        ctx = _current_case.get()
        pc.operation = ctx.case_id if ctx else "harness"
        self.provider_calls.append(pc)
        if ctx is not None:
            ctx.provider_calls.append(pc)

    def uninstall(self) -> None:
        for obj, name, original in reversed(self._undo):
            setattr(obj, name, original)
        self._undo.clear()
        self._installed = False


# --------------------------------------------------------------------------------------------------------------------
# aggregation


def summarize_llm_calls(calls: list[LLMCall]) -> dict[str, Any]:
    """Technical metrics over counted (non-setup) gateway calls."""
    counted = [c for c in calls if not c.setup]
    latencies = [c.latency_ms for c in counted if not c.degraded]
    live = [c for c in counted if not c.degraded and not c.from_replay]
    errors: dict[str, int] = {}
    for c in counted:
        for a in c.attempts:
            if a.error_category:
                errors[a.error_category] = errors.get(a.error_category, 0) + 1
    by_tier: dict[str, int] = {}
    for c in counted:
        by_tier[c.tier] = by_tier.get(c.tier, 0) + 1
    models = sorted({c.model for c in counted if c.model})
    return {
        "calls": len(counted),
        "live_ok_calls": len(live),
        "degraded_calls": sum(c.degraded for c in counted),
        "replayed_calls": sum(c.from_replay for c in counted),
        "non_json_answers": sum(c.non_json for c in counted),
        "gateway_retries": sum(c.gateway_retries for c in counted),
        "provider_attempts": sum(len(c.attempts) for c in counted),
        "provider_error_attempts": sum(errors.values()),
        "provider_errors_by_category": errors,
        "tokens_in": sum(c.tokens_in for c in counted),
        "tokens_out": sum(c.tokens_out for c in counted),
        "latency_ms_avg": _r(mean(latencies)),
        "latency_ms_p50": _r(percentile(latencies, 50)),
        "latency_ms_p95": _r(percentile(latencies, 95)),
        "latency_ms_max": _r(max(latencies) if latencies else None),
        "calls_by_tier": by_tier,
        "models": models,
    }


def _r(value: float | None, digits: int = 1) -> float | None:
    return None if value is None else round(value, digits)
