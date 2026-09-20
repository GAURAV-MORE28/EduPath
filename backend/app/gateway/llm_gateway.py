"""LLM Gateway.

Design §7, §33.2, §33.5, §38.3 and ARCHITECTURE_CONTRACTS.md §11/§14:
provider-agnostic model routing by tier (small / mid / strong), a bounded
retry policy, and a durable record/replay cache so the whole stack can run
offline for a demo.

Resolution order for one `complete()` call (it never raises):

  1. `REPLAY_MODE=true`  -> the recorded response for this prompt hash, if any
                            (deterministic / offline; the trace shows a replay).
  2. a live provider     -> `LLM_PROVIDER != "none"`: call it (timeout
                            `LLM_TIMEOUT_S`, backoff x2 on transport/5xx/429).
                            A successful, non-degraded answer is *recorded*
                            when `LLM_RECORD=true` or `DEMO_MODE=true`.
  3. the recorded answer -> live failed / no provider: replay (outage fallback).
  4. degrade             -> `LLMResponse(degraded=True)`; callers fall through
                            to their deterministic path (fallback planner,
                            deterministic extractor, templated text, item bank).

Every call reports itself to the request's run (`note_llm_call`) and adds an
audit-only `LLM Gateway` step (latency, tokens, cost, status).
"""
from __future__ import annotations

import asyncio
import hashlib
import time
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Awaitable, Callable

from pydantic import BaseModel
from sqlalchemy import select

from app.config import Settings, get_settings
from app.gateway.providers import (
    ProviderError,
    ProviderResult,
    call_anthropic,
    call_openai_compatible,
    extract_json_object,
)
from app.logging_config import get_logger
from app.observability.context import note_llm_call
from app.sse.trace import emit

logger = get_logger(__name__)


class ModelTier(str, Enum):
    SMALL = "small"
    MID = "mid"
    STRONG = "strong"


class LLMRequest(BaseModel):
    tier: ModelTier
    system_prompt: str
    user_prompt: str
    schema_name: str
    temperature: float = 0.0


class LLMResponse(BaseModel):
    raw_text: str
    parsed: dict[str, Any] | None = None
    degraded: bool = False
    from_replay: bool = False
    tokens_in: int = 0
    tokens_out: int = 0
    model: str = ""
    latency_ms: float = 0.0
    error: str | None = None


def prompt_hash(request: LLMRequest) -> str:
    payload = request.model_dump_json().encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class ReplayCache(ABC):
    @abstractmethod
    async def get(self, key: str) -> LLMResponse | None: ...

    @abstractmethod
    async def put(self, key: str, response: LLMResponse, meta: dict[str, str] | None = None) -> None: ...


class InMemoryReplayCache(ReplayCache):
    """Process-local replay cache: the default when no provider/replay/record
    flag is set (nothing would ever be recorded into it anyway)."""

    def __init__(self) -> None:
        self._store: dict[str, LLMResponse] = {}

    async def get(self, key: str) -> LLMResponse | None:
        return self._store.get(key)

    async def put(self, key: str, response: LLMResponse, meta: dict[str, str] | None = None) -> None:
        self._store[key] = response


_SQLITE_DEV_CACHE = InMemoryReplayCache()


class DbReplayCache(ReplayCache):
    """Postgres-backed record/replay table (`llm_replay_entries`), the durable
    cache ARCHITECTURE_CONTRACTS.md §14 requires. Uses its own short sessions
    and never raises: a broken cache degrades to "no recording", not a failed call.

    On SQLite (dev/test only) the app's in-memory engine is a single shared
    connection, so a second session's close would roll back the *request's*
    pending writes; there the default cache is process-local instead. Pass an
    explicit `session_factory` (tests do) to exercise the real table."""

    def __init__(self, session_factory: Any | None = None) -> None:
        self._session_factory = session_factory
        self._fallback: InMemoryReplayCache | None = None
        if session_factory is None:
            from app.db.session import SessionLocal, engine

            if engine.dialect.name == "sqlite":
                self._fallback = _SQLITE_DEV_CACHE
            else:
                self._session_factory = SessionLocal

    async def get(self, key: str) -> LLMResponse | None:
        if self._fallback is not None:
            return await self._fallback.get(key)
        try:
            from app.db.models import LlmReplayEntry

            async with self._session_factory() as session:
                row = (await session.execute(select(LlmReplayEntry).where(LlmReplayEntry.prompt_hash == key))).scalar_one_or_none()
            return LLMResponse(**row.response) if row is not None else None
        except Exception:  # noqa: BLE001
            logger.warning("edupath.gateway.replay_get_failed", exc_info=True)
            return None

    async def put(self, key: str, response: LLMResponse, meta: dict[str, str] | None = None) -> None:
        if self._fallback is not None:
            await self._fallback.put(key, response, meta)
            return
        try:
            from app.db.models import LlmReplayEntry

            meta = meta or {}
            async with self._session_factory() as session:
                row = await session.get(LlmReplayEntry, key)
                payload = response.model_copy(update={"from_replay": False}).model_dump(mode="json")
                if row is None:
                    session.add(
                        LlmReplayEntry(prompt_hash=key, schema_name=meta.get("schema_name", ""), tier=meta.get("tier", ""), response=payload)
                    )
                else:
                    row.response = payload
                await session.commit()
        except Exception:  # noqa: BLE001
            logger.warning("edupath.gateway.replay_put_failed", exc_info=True)


ProviderCall = Callable[[Settings, LLMRequest], Awaitable[ProviderResult]]


async def _default_provider_call(settings: Settings, request: LLMRequest) -> ProviderResult:
    if settings.llm_provider == "anthropic":
        return await call_anthropic(
            settings,
            tier=request.tier.value,
            system_prompt=request.system_prompt,
            user_prompt=request.user_prompt,
            temperature=request.temperature,
        )
    if settings.llm_provider in ("groq", "huggingface"):
        return await call_openai_compatible(
            settings,
            provider=settings.llm_provider,
            tier=request.tier.value,
            system_prompt=request.system_prompt,
            user_prompt=request.user_prompt,
            temperature=request.temperature,
        )
    raise ProviderError(f"unsupported LLM_PROVIDER '{settings.llm_provider}'", retryable=False)


class LLMGateway:
    """Routes structured-output requests to a provider tier with a bounded
    retry policy (max 2, ARCHITECTURE_CONTRACTS.md §6/§11) and the
    record/replay fallback described in the module docstring."""

    max_retries = 2
    backoff_base_s = 0.25

    def __init__(self, cache: ReplayCache | None = None, provider_call: ProviderCall | None = None) -> None:
        self.settings = get_settings()
        self.cache = cache or self._default_cache()
        self._provider_call = provider_call or _default_provider_call

    def _default_cache(self) -> ReplayCache:
        s = self.settings
        if s.llm_provider != "none" or s.replay_mode or s.llm_record or s.demo_mode:
            return DbReplayCache()
        return InMemoryReplayCache()

    async def complete(self, request: LLMRequest) -> LLMResponse:
        started = time.perf_counter()
        s = self.settings
        key = prompt_hash(request)
        response: LLMResponse | None = None
        error: str | None = None

        if s.replay_mode:
            response = await self._replayed(key)

        if response is None and s.llm_provider != "none":
            response, error = await self._live(request)
            if response is not None and (s.llm_record or s.demo_mode):
                await self.cache.put(key, response, {"schema_name": request.schema_name, "tier": request.tier.value})

        if response is None and not s.replay_mode:
            response = await self._replayed(key)

        if response is None:
            # No provider / provider down and nothing recorded: degrade deterministically
            # (design P7, ARCHITECTURE_CONTRACTS.md §11). Degraded answers are never recorded.
            response = LLMResponse(raw_text="", parsed=None, degraded=True, error=error)

        latency_ms = (time.perf_counter() - started) * 1000.0
        response = response.model_copy(update={"latency_ms": round(latency_ms, 3)})
        cost = (response.tokens_in * s.llm_cost_per_1k_input_usd + response.tokens_out * s.llm_cost_per_1k_output_usd) / 1000.0
        note_llm_call(
            tokens_in=response.tokens_in,
            tokens_out=response.tokens_out,
            cost_usd=cost,
            replayed=response.from_replay,
            degraded=response.degraded,
        )
        origin = "replay" if response.from_replay else "degraded" if response.degraded else "live"
        await emit(
            "LLM Gateway",
            "tool_call",
            f"{request.schema_name} [{request.tier.value}] -> {origin}" + (f" ({response.error})" if response.error else ""),
            output_ref=key[:16],
            duration_ms=latency_ms,
            status="degraded" if response.degraded else "ok",
            tokens_in=response.tokens_in,
            tokens_out=response.tokens_out,
            cost_usd=cost,
            publish=False,
        )
        return response

    async def _replayed(self, key: str) -> LLMResponse | None:
        cached = await self.cache.get(key)
        if cached is None or cached.degraded:
            return None
        return cached.model_copy(update={"from_replay": True})

    async def _live(self, request: LLMRequest) -> tuple[LLMResponse | None, str | None]:
        last_error: str | None = None
        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            last_exc = None
            try:
                result = await asyncio.wait_for(
                    self._provider_call(self.settings, request), timeout=self.settings.llm_timeout_s + 1.0
                )
            except asyncio.TimeoutError:
                last_error = "provider timeout"
            except ProviderError as exc:
                last_error = str(exc)
                last_exc = exc
                if not exc.retryable:
                    break
            except Exception as exc:  # noqa: BLE001 -- the gateway must never raise into an agent
                last_error = f"{type(exc).__name__}"
                logger.warning("edupath.gateway.provider_unexpected", exc_info=True)
            else:
                return (
                    LLMResponse(
                        raw_text=result.text,
                        parsed=extract_json_object(result.text),
                        tokens_in=result.tokens_in,
                        tokens_out=result.tokens_out,
                        model=result.model,
                    ),
                    None,
                )
            if attempt < self.max_retries:
                delay = self.backoff_base_s * (2**attempt)
                if isinstance(last_exc, ProviderError) and last_exc.retry_after:
                    delay = max(delay, min(last_exc.retry_after, 15.0))  # honour a 429's Retry-After, bounded
                await asyncio.sleep(delay)
        logger.warning("edupath.gateway.live_failed", error=last_error)
        return None, last_error
