"""LLM Gateway (Phase 12): record/replay, the live-first -> recorded -> degraded
resolution order, bounded retries, and "never raises into an agent" (design §30,
§33.5, §38.3; ARCHITECTURE_CONTRACTS.md §11/§14)."""
from __future__ import annotations

import json

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.db.base import Base
from app.gateway.llm_gateway import (
    DbReplayCache,
    InMemoryReplayCache,
    LLMGateway,
    LLMRequest,
    LLMResponse,
    ModelTier,
    prompt_hash,
)
from app.gateway.providers import ProviderError, ProviderResult, call_anthropic, extract_json_object
from app.observability.context import RunContext, current_run

pytestmark = pytest.mark.asyncio


def _request(user: str = "hello") -> LLMRequest:
    return LLMRequest(tier=ModelTier.MID, system_prompt="sys", user_prompt=user, schema_name="Test")


@pytest.fixture
def settings(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "llm_provider", "test-provider")
    monkeypatch.setattr(s, "replay_mode", False)
    monkeypatch.setattr(s, "llm_record", False)
    monkeypatch.setattr(s, "demo_mode", False)
    monkeypatch.setattr(s, "llm_cost_per_1k_input_usd", 1.0)
    monkeypatch.setattr(s, "llm_cost_per_1k_output_usd", 2.0)
    return s


def _gateway(provider_call, cache=None) -> LLMGateway:
    gateway = LLMGateway(cache=cache or InMemoryReplayCache(), provider_call=provider_call)
    gateway.backoff_base_s = 0.0
    return gateway


async def test_no_provider_degrades_deterministically_and_never_records(monkeypatch):
    monkeypatch.setattr(get_settings(), "llm_provider", "none")
    monkeypatch.setattr(get_settings(), "replay_mode", False)
    cache = InMemoryReplayCache()
    response = await LLMGateway(cache=cache).complete(_request())
    assert response.degraded and response.raw_text == "" and response.parsed is None
    assert await cache.get(prompt_hash(_request())) is None  # a degraded stub is never a "recorded" answer


async def test_live_success_parses_json_and_reports_tokens_and_cost(settings):
    async def provider(_settings, request):
        return ProviderResult(text='```json\n{"ok": true}\n```', tokens_in=1000, tokens_out=500, model="m1")

    ctx = RunContext(run_id="run-gw-1", client_supplied=False)
    token = current_run.set(ctx)
    try:
        response = await _gateway(provider).complete(_request())
    finally:
        current_run.reset(token)
    assert not response.degraded and not response.from_replay
    assert response.parsed == {"ok": True} and response.tokens_in == 1000 and response.model == "m1"
    assert ctx.llm_calls == 1 and ctx.tokens_in == 1000 and ctx.tokens_out == 500
    assert ctx.cost_usd == pytest.approx(1.0 + 1.0)  # 1000/1k * $1 + 500/1k * $2
    step = ctx.steps[-1]
    assert step.actor == "LLM Gateway" and step.tokens_in == 1000 and step.status == "ok" and step.duration_ms >= 0


async def test_record_then_outage_falls_back_to_the_recorded_response(settings, monkeypatch):
    monkeypatch.setattr(settings, "llm_record", True)
    cache = InMemoryReplayCache()
    calls = {"n": 0}

    async def live(_s, _r):
        calls["n"] += 1
        return ProviderResult(text='{"answer": 42}', tokens_in=10, tokens_out=5)

    recorded = await _gateway(live, cache).complete(_request())
    assert recorded.parsed == {"answer": 42} and not recorded.from_replay

    async def down(_s, _r):
        raise ProviderError("provider returned 503")

    replayed = await _gateway(down, cache).complete(_request())
    assert replayed.from_replay and replayed.parsed == {"answer": 42} and not replayed.degraded

    # a prompt that was never recorded still degrades rather than raising
    unseen = await _gateway(down, cache).complete(_request("something else"))
    assert unseen.degraded and unseen.error == "provider returned 503"


async def test_replay_mode_serves_recorded_responses_without_calling_the_provider(settings, monkeypatch):
    monkeypatch.setattr(settings, "replay_mode", True)
    cache = InMemoryReplayCache()
    await cache.put(prompt_hash(_request()), LLMResponse(raw_text="{}", parsed={"from": "tape"}))

    async def must_not_be_called(_s, _r):
        raise AssertionError("replay mode must not hit the live provider for a recorded prompt")

    response = await _gateway(must_not_be_called, cache).complete(_request())
    assert response.from_replay and response.parsed == {"from": "tape"}


async def test_transient_failures_are_retried_at_most_twice(settings):
    calls = {"n": 0}

    async def flaky(_s, _r):
        calls["n"] += 1
        if calls["n"] < 3:
            raise ProviderError("provider returned 500")
        return ProviderResult(text='{"ok": 1}')

    response = await _gateway(flaky).complete(_request())
    assert calls["n"] == 3 and not response.degraded

    calls["n"] = 0

    async def always_down(_s, _r):
        calls["n"] += 1
        raise ProviderError("provider returned 500")

    response = await _gateway(always_down).complete(_request("x"))
    assert calls["n"] == 3 and response.degraded  # 1 attempt + max_retries(2), then degrade


async def test_non_retryable_errors_and_unexpected_exceptions_degrade_without_raising(settings):
    calls = {"n": 0}

    async def rejected(_s, _r):
        calls["n"] += 1
        raise ProviderError("provider rejected the request (400)", retryable=False)

    assert (await _gateway(rejected).complete(_request())).degraded and calls["n"] == 1

    async def broken(_s, _r):
        raise RuntimeError("boom")

    response = await _gateway(broken).complete(_request("y"))
    assert response.degraded and response.error == "RuntimeError"


async def test_a_slow_provider_times_out_and_degrades(settings, monkeypatch):
    import asyncio

    monkeypatch.setattr(settings, "llm_timeout_s", 0.0)

    async def slow(_s, _r):
        await asyncio.sleep(5)
        return ProviderResult(text="{}")

    gateway = _gateway(slow)
    gateway.max_retries = 0
    response = await gateway.complete(_request())
    assert response.degraded and response.error == "provider timeout"


async def test_unsupported_provider_name_degrades_instead_of_crashing(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "llm_provider", "no-such-provider")
    monkeypatch.setattr(s, "replay_mode", False)
    response = await LLMGateway(cache=InMemoryReplayCache()).complete(_request())
    assert response.degraded and "unsupported" in (response.error or "")


async def test_other_gateways_do_not_raise_for_a_configured_provider(monkeypatch):
    """Regression (Phase 12): any LLM_PROVIDER other than "none" used to make these raise
    NotImplementedError -> a 500 on intake, upload and planning."""
    from app.gateway.embedding_gateway import get_embedding_gateway
    from app.gateway.vlm_gateway import get_vlm_gateway
    from app.gateway.web_fallback_gateway import get_web_fallback_gateway

    monkeypatch.setattr(get_settings(), "llm_provider", "anthropic")
    assert len(await get_embedding_gateway().embed("chain rule")) > 0
    assert get_vlm_gateway() is not None and get_web_fallback_gateway() is not None


# -- durable replay table --------------------------------------------------------------------------


@pytest.fixture
async def replay_session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    await engine.dispose()


async def test_db_replay_cache_round_trips_and_upserts(replay_session_factory):
    cache = DbReplayCache(session_factory=replay_session_factory)
    key = prompt_hash(_request())
    assert await cache.get(key) is None
    await cache.put(key, LLMResponse(raw_text="a", parsed={"v": 1}, tokens_in=3), {"schema_name": "Test", "tier": "mid"})
    got = await cache.get(key)
    assert got is not None and got.parsed == {"v": 1} and got.tokens_in == 3
    await cache.put(key, LLMResponse(raw_text="b", parsed={"v": 2}))
    assert (await cache.get(key)).parsed == {"v": 2}  # re-recording replaces, never duplicates


async def test_db_replay_cache_never_raises_when_the_table_is_missing():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")  # no tables created
    cache = DbReplayCache(session_factory=async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession))
    assert await cache.get("k") is None
    await cache.put("k", LLMResponse(raw_text="x"))  # swallowed
    await engine.dispose()


async def test_a_degraded_entry_in_the_cache_is_never_replayed(settings):
    cache = InMemoryReplayCache()
    await cache.put(prompt_hash(_request()), LLMResponse(raw_text="", degraded=True))

    async def down(_s, _r):
        raise ProviderError("provider returned 503", retryable=False)

    assert (await _gateway(down, cache).complete(_request())).degraded


# -- the Anthropic adapter ------------------------------------------------------------------------------


def _anthropic_settings(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "llm_provider", "anthropic")
    monkeypatch.setattr(s, "llm_api_key", "k")
    monkeypatch.setattr(s, "llm_mid_model", "claude-test")
    return s


async def test_anthropic_adapter_parses_text_and_usage(monkeypatch):
    s = _anthropic_settings(monkeypatch)
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"], seen["body"], seen["key"] = str(request.url), json.loads(request.content), request.headers["x-api-key"]
        return httpx.Response(200, json={"content": [{"type": "text", "text": '{"a": 1}'}], "usage": {"input_tokens": 7, "output_tokens": 3}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await call_anthropic(s, tier="mid", system_prompt="S", user_prompt="U", temperature=0.0, client=client)
    assert result.text == '{"a": 1}' and (result.tokens_in, result.tokens_out) == (7, 3) and result.model == "claude-test"
    assert seen["url"].endswith("/v1/messages") and seen["body"]["model"] == "claude-test" and seen["key"] == "k"


@pytest.mark.parametrize("status_code,retryable", [(500, True), (429, True), (400, False), (401, False)])
async def test_anthropic_adapter_error_classification(monkeypatch, status_code, retryable):
    s = _anthropic_settings(monkeypatch)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(status_code, json={}))) as client:
        with pytest.raises(ProviderError) as exc:
            await call_anthropic(s, tier="mid", system_prompt="S", user_prompt="U", temperature=0.0, client=client)
    assert exc.value.retryable is retryable


async def test_anthropic_adapter_without_key_or_model_is_a_non_retryable_error(monkeypatch):
    s = _anthropic_settings(monkeypatch)
    monkeypatch.setattr(s, "llm_api_key", "")
    with pytest.raises(ProviderError) as exc:
        await call_anthropic(s, tier="mid", system_prompt="S", user_prompt="U", temperature=0.0)
    assert exc.value.retryable is False


async def test_extract_json_object_handles_fences_prose_and_garbage():
    assert extract_json_object('{"a": 1}') == {"a": 1}
    assert extract_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json_object('Sure! Here you go: {"a": {"b": 2}} hope that helps') == {"a": {"b": 2}}
    assert extract_json_object("no json here") is None
    assert extract_json_object("[1, 2, 3]") is None  # only objects are valid agent output
