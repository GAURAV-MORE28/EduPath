"""LLM Gateway interface.

Design doc §7, §33.2, ARCHITECTURE_CONTRACTS.md §14: provider-agnostic model
routing by tier (small / mid / strong), structured-output enforcement, and a
record/replay cache so the whole stack can run offline for a demo. This phase
defines the interface and a replay-only stub; real provider calls and the
record/replay table are implemented alongside the first agent that needs them
(Phase 2, Profiler).
"""
from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any

from pydantic import BaseModel

from app.config import get_settings


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


def prompt_hash(request: LLMRequest) -> str:
    payload = request.model_dump_json().encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class ReplayCache(ABC):
    @abstractmethod
    async def get(self, key: str) -> LLMResponse | None: ...

    @abstractmethod
    async def put(self, key: str, response: LLMResponse) -> None: ...


class InMemoryReplayCache(ReplayCache):
    """Process-local replay cache. Phase 1 stub — a Postgres-backed table
    (record/replay per ARCHITECTURE_CONTRACTS.md §14) replaces this once the
    first real agent call exists."""

    def __init__(self) -> None:
        self._store: dict[str, LLMResponse] = {}

    async def get(self, key: str) -> LLMResponse | None:
        return self._store.get(key)

    async def put(self, key: str, response: LLMResponse) -> None:
        self._store[key] = response


class LLMGateway:
    """Routes structured-output requests to a provider tier, with a bounded
    retry policy (max 2, per ARCHITECTURE_CONTRACTS.md §6/§11) and a
    replay-cache fallback. No provider is wired in Phase 1 — agents that need
    real completions are implemented in the phases that own them."""

    max_retries = 2

    def __init__(self, cache: ReplayCache | None = None) -> None:
        self.settings = get_settings()
        self.cache = cache or InMemoryReplayCache()

    async def complete(self, request: LLMRequest) -> LLMResponse:
        key = prompt_hash(request)

        if self.settings.replay_mode:
            cached = await self.cache.get(key)
            if cached is not None:
                cached = cached.model_copy(update={"from_replay": True})
                return cached

        if self.settings.llm_provider == "none":
            # No provider configured: degrade deterministically rather than
            # hard-fail (design P7, ARCHITECTURE_CONTRACTS.md §11).
            response = LLMResponse(raw_text="", parsed=None, degraded=True)
            await self.cache.put(key, response)
            return response

        raise NotImplementedError(
            "Real provider routing is implemented by the phase that owns the "
            "first LLM agent (Phase 2, Profiler)."
        )
