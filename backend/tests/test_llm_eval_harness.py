"""Offline tests for the live-LLM evaluation harness itself (tests/evaluation/live/, scripts/evaluate_llm.py).

These never touch a real provider: they check the harness's own arithmetic, redaction, live-mode refusal and that the
call recorder *wraps* (never replaces) the gateway. The live evaluation is run by `python scripts/evaluate_llm.py`.
"""
from __future__ import annotations

import json

import pytest

from app.config import get_settings
from app.gateway import llm_gateway as llm
from app.gateway.llm_gateway import InMemoryReplayCache, LLMGateway, LLMRequest, ModelTier
from app.gateway.providers import ProviderError, ProviderResult
from tests.evaluation.live import instrument as ins
from tests.evaluation.live import report as rep
from tests.evaluation.live import runner


def test_percentile_is_nearest_rank_and_never_invents_a_number():
    assert ins.percentile([], 50) is None
    assert ins.percentile([10.0], 95) == 10.0
    assert ins.percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 50) == 5
    assert ins.percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 95) == 10
    assert ins.mean([]) is None


@pytest.mark.parametrize(
    ("message", "category"),
    [
        ("provider returned 429", "rate_limit"), ("provider timeout", "timeout"), ("transport error: ConnectError", "transport"),
        ("provider returned 503", "server_error"), ("provider rejected the request (413): too big", "payload_too_large"),
        ("provider rejected the request (400): bad", "client_error"), ("empty provider response", "empty_response"),
        ("unparseable provider response", "unparseable_response"), ("no model/API key configured for tier 'mid'", "not_configured"),
        (None, None), ("something else entirely", "other"),
    ],
)
def test_error_categories(message, category):
    assert ins.categorize_error(message) == category


def test_redact_scrubs_registered_values_and_token_shapes():
    ins.register_secrets("s3cr3t-value-123")
    text = "failed with key s3cr3t-value-123 and header Authorization: Bearer abcdefghijklmnop and gsk_ABCDEFGHIJKL and hf_ABCDEFGHIJKL"
    out = ins.redact(text)
    for leaked in ("s3cr3t-value-123", "abcdefghijklmnop", "gsk_ABCDEFGHIJKL", "hf_ABCDEFGHIJKL"):
        assert leaked not in out
    assert "[REDACTED]" in out
    ins._SECRET_VALUES.discard("s3cr3t-value-123")


def test_live_mode_refuses_a_disabled_provider(monkeypatch):
    settings = get_settings()  # the suite pins LLM_PROVIDER=none
    with pytest.raises(runner.LiveConfigError):
        runner.require_live(settings)
    monkeypatch.setattr(settings, "llm_provider", "groq")
    monkeypatch.setattr(settings, "llm_api_key", "")
    with pytest.raises(runner.LiveConfigError):
        runner.require_live(settings)
    monkeypatch.setattr(settings, "llm_api_key", "k" * 12)
    monkeypatch.setattr(settings, "llm_small_model", "s")
    monkeypatch.setattr(settings, "llm_mid_model", "m")
    monkeypatch.setattr(settings, "llm_strong_model", "l")
    present = runner.require_live(settings)
    assert present["LLM_API_KEY"] is True and all(isinstance(v, bool) for v in present.values())  # names -> booleans, never values


async def _gateway_call(monkeypatch, fake):
    settings = get_settings()
    monkeypatch.setattr(settings, "llm_provider", "groq")
    monkeypatch.setattr(llm, "_default_provider_call", fake)
    recorder = ins.Recorder().install()
    ctx = ins.CaseContext("planner", "case-1")
    try:
        with ins.case_scope(ctx):
            gateway = LLMGateway(cache=InMemoryReplayCache())
            gateway.backoff_base_s = 0.0
            response = await gateway.complete(LLMRequest(tier=ModelTier.MID, system_prompt="s", user_prompt="u", schema_name="Probe"))
    finally:
        recorder.uninstall()
    return response, ctx, recorder


async def test_recorder_wraps_the_real_call_path_and_counts_gateway_retries(monkeypatch):
    calls = {"n": 0}

    async def flaky(settings, request):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ProviderError("provider returned 429", retry_after=None)
        return ProviderResult(text='{"ok": true}', tokens_in=7, tokens_out=3, model="m-1")

    response, ctx, recorder = await _gateway_call(monkeypatch, flaky)
    assert response.parsed == {"ok": True} and not response.degraded  # the provider's real answer is passed through untouched
    assert calls["n"] == 2
    (call,) = ctx.llm_calls
    assert call.gateway_retries == 1 and [a.error_category for a in call.attempts] == ["rate_limit", None]
    assert (call.model, call.tokens_in, call.tokens_out, call.degraded, call.setup) == ("m-1", 7, 3, False, False)
    summary = ins.summarize_llm_calls(recorder.llm_calls)
    assert summary["calls"] == 1 and summary["gateway_retries"] == 1 and summary["provider_errors_by_category"] == {"rate_limit": 1}
    assert llm._default_provider_call is flaky  # uninstall restored the original


async def test_a_provider_outage_is_recorded_as_degraded_never_as_success(monkeypatch):
    async def down(settings, request):
        raise ProviderError("provider returned 503")

    response, ctx, _ = await _gateway_call(monkeypatch, down)
    (call,) = ctx.llm_calls
    assert response.degraded and call.degraded and call.error_category == "server_error" and len(call.attempts) == 3


async def test_setup_mode_refuses_the_provider_without_calling_it_and_is_excluded_from_metrics(monkeypatch):
    called = {"n": 0}

    async def should_not_run(settings, request):
        called["n"] += 1
        return ProviderResult(text="{}", model="m")

    settings = get_settings()
    monkeypatch.setattr(settings, "llm_provider", "groq")
    monkeypatch.setattr(llm, "_default_provider_call", should_not_run)
    recorder = ins.Recorder().install()
    try:
        with ins.case_scope(ins.CaseContext("planner", "c")), ins.setup_mode():
            response = await LLMGateway(cache=InMemoryReplayCache()).complete(
                LLMRequest(tier=ModelTier.MID, system_prompt="s", user_prompt="u", schema_name="Setup")
            )
    finally:
        recorder.uninstall()
    assert called["n"] == 0 and response.degraded
    assert recorder.llm_calls[0].setup is True
    assert ins.summarize_llm_calls(recorder.llm_calls)["calls"] == 0  # scaffolding never inflates the numbers


def _case(area, case_id, status="pass", **kw):
    base = {
        "area": area, "case_id": case_id, "status": status, "latency_ms": 100.0, "llm_calls": 1, "llm_degraded": 0, "gateway_retries": 0, "agent_retries": 0,
        "attempts": 1, "fallback": False, "schema_valid": True, "validator_pass": True, "metrics": {}, "checks": {}, "failed_checks": [],
        "examples": [], "notes": [], "error": None, "skip_reason": None,
    }
    base.update(kw)
    return base


def test_technical_metrics_count_statuses_and_leave_unmeasured_rates_as_none():
    cases = [
        _case("planner", "a"), _case("planner", "b", status="fallback", fallback=True, validator_pass=False),
        _case("planner", "c", status="skipped", llm_calls=0, schema_valid=None, validator_pass=None, fallback=None),
        _case("gap", "d", llm_calls=0, schema_valid=None, validator_pass=None, fallback=None),
    ]
    calls = [
        {"latency_ms": 1000.0, "degraded": False, "attempts": 1, "attempt_errors": [], "tokens_in": 10, "tokens_out": 5},
        {"latency_ms": 3000.0, "degraded": False, "attempts": 2, "attempt_errors": ["rate_limit"], "tokens_in": 20, "tokens_out": 5},
    ]
    t = rep.technical_metrics(cases, calls, [])
    assert (t["total_cases"], t["successful_cases"], t["fallback_cases"], t["skipped_cases"]) == (4, 2, 1, 1)
    assert t["validator_pass_rate"] == 0.5 and t["schema_valid_rate"] == 1.0 and t["fallback_rate"] == 0.5
    assert t["gateway_retries"] == 1 and t["provider_errors"]["llm_attempt_errors_by_category"] == {"rate_limit": 1}
    assert t["llm_call_latency_ms"]["p50"] == 1000 and t["llm_call_latency_ms"]["p95"] == 3000
    empty = rep.technical_metrics([], [], [])
    assert empty["schema_valid_rate"] is None and empty["llm_call_latency_ms"]["p50"] is None  # never a fabricated 0


def test_quality_metrics_are_micro_averaged_and_skip_unrun_cases():
    p1 = _case("profiling", "p1", metrics={"tp": 3, "fp": 1, "fn": 1, "forbidden_hits": 0, "extracted": 4, "claims": 4, "mapped_claims": 4,
                                           "unsupported_claims": 0, "span_present_ok": 4, "span_fidelity_ok": 4, "dropped_unverified": 0,
                                           "dropped_injection": 0, "first_try_schema_valid": True, "conf_right": [1.0], "conf_wrong": [], "tiers": {"E0": 4}})
    p2 = _case("profiling", "p2", status="skipped", llm_calls=0)
    p3 = _case("profiling", "p3", status="provider_error", metrics={"tp": 0, "fp": 0, "fn": 9})
    q = rep.quality_metrics({"profiling": [p1, p2, p3]})["profiling"]
    assert q["skill precision (micro)"]["value"] == 0.75 and q["skill recall (micro)"]["value"] == 0.75  # p2/p3 do not count
    assert q["evidence-tier assignment accuracy"]["value"] is None and "not scored" in q["evidence-tier assignment accuracy"]["note"]


def test_markdown_report_renders_and_never_contains_secret_shapes():
    cases = [_case("known_issues", "auth", llm_calls=0, metrics={"cookie_forgeable": True}, schema_valid=None, validator_pass=None, fallback=None)]
    by_area = {"known_issues": cases}
    report = {
        "meta": {"mode": "live", "suite": "smoke", "timestamp_utc": "2026-01-01T00:00:00Z", "git_commit": "abc1234", "git_dirty": False, "python": "python 3",
                 "providers": {k: "x" for k in ("llm_provider", "llm_small_model", "llm_mid_model", "llm_strong_model", "embedding_provider", "embedding_model", "vlm_provider", "vlm_model", "web_search_provider")},
                 "credentials_present": {"LLM_API_KEY": True}, "dataset": {"graph_version": "g", "gold_hash": "h"}, "prompt_versions": {"tutor": "deadbeef"}},
        "technical": rep.technical_metrics(cases, [], []), "quality": rep.quality_metrics(by_area), "cases": cases, "cases_by_area": by_area,
        "llm_calls": [], "offline_reference": {},
    }
    md = rep.render_markdown(report)
    assert "Known-issue probes" in md and "session cookie forgeable" in md and "LLM_API_KEY" in md
    for pattern in ins._TOKEN_PATTERNS:
        assert not pattern.search(md)
    json.dumps(report, default=runner._json_default)  # the JSON report serializes


def test_gold_live_file_is_consistent_with_the_offline_gold_sets():
    from tests.evaluation.live import scenarios as sc
    from tests.evaluation.metrics import load_gold

    gold = sc.load_live_gold()
    resume_ids = {r["id"] for r in load_gold("resumes.json")}
    for suite in gold["suites"].values():
        assert suite["resumes"] == "all" or set(suite["resumes"]) <= resume_ids
    qids = {q["id"] for q in gold["tutor_questions"]}
    assert len(qids) == len(gold["tutor_questions"]) == 17
    assert set(gold["suites"]["smoke"]["tutor_questions"]) <= qids
    assert {p["id"] for p in gold["personas"]} >= set(gold["suites"]["smoke"]["personas"])


def _report(tag, cases, calls=()):
    return {"meta": {"timestamp_utc": tag, "suite": "full", "mode": "live"}, "cases": cases, "llm_calls": list(calls), "provider_calls": [], "throttle_events": []}


def test_merge_keeps_the_best_measured_result_per_case_and_never_invents_one():
    call = lambda op: {"operation": op, "schema": "S", "tier": "mid", "latency_ms": 10.0, "attempts": 1, "attempt_errors": [], "degraded": False, "tokens_in": 1, "tokens_out": 1}  # noqa: E731
    r1 = _report("t1", [_case("tutor", "q-a"), _case("tutor", "q-b", status="provider_error"), _case("tutor", "q-c", status="skipped", llm_calls=0)],
                 [call("q-a"), call("q-b")])
    r2 = _report("t2", [_case("tutor", "q-a", latency_ms=999.0), _case("tutor", "q-b"), _case("tutor", "q-d")], [call("q-a"), call("q-b"), call("q-d")])
    merged = runner.merge_reports([r1, r2])
    by_id = {c["case_id"]: c for c in merged["cases"]}
    assert by_id["q-a"]["source_run"] == "t1/full" and by_id["q-a"]["latency_ms"] == 100.0  # the earlier measured result wins ties
    assert by_id["q-b"]["source_run"] == "t2/full" and by_id["q-b"]["status"] == "pass"  # measured beats provider_error
    assert by_id["q-c"]["status"] == "skipped"  # nobody measured it: it stays skipped, it is not invented
    assert merged["technical"]["total_cases"] == 4 and merged["technical"]["skipped_cases"] == 1
    assert len(merged["llm_calls"]) == 3  # q-a (t1), q-b (t2), q-d (t2): no double counting of superseded attempts
    assert merged["meta"]["merged_from"] == ["t1/full", "t2/full"]
