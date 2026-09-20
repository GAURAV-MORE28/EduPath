"""Orchestration of the live LLM evaluation (CLI: `scripts/evaluate_llm.py`).

    prepare_environment()  -> BEFORE any `app` import: in-memory SQLite, replay/record/demo off, temp storage
    require_live()         -> refuse to run "live" against a disabled provider (never silently offline)
    run_evaluation()       -> bootstrap the catalog (live embeddings), run the suite's cases, build the report

Pacing / quota: cases run sequentially with a small gap; a per-case circuit breaker aborts the remaining LLM-bearing
cases after consecutive rate-limited cases (they are reported as skipped/aborted, not as model failures).
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import subprocess
import sys
import tempfile
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

BACKEND_ROOT = Path(__file__).resolve().parents[3]
REPORT_DIR = BACKEND_ROOT / "reports" / "llm_eval"
AREAS_LLM = {"profiling", "planner", "assessor", "reflection", "tutor", "vision"}


class LiveConfigError(RuntimeError):
    pass


def prepare_environment() -> None:
    """Environment variables outrank `.env`, so this pins the harness-owned settings and leaves the provider
    settings (LLM_PROVIDER, keys, models, ...) to `.env`."""
    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"  # never touch a real database
    os.environ.update({"DEMO_MODE": "false", "REPLAY_MODE": "false", "LLM_RECORD": "false", "AUTO_SEED_CATALOG": "false"})
    os.environ.setdefault("DOCUMENT_STORAGE_DIR", tempfile.mkdtemp(prefix="edupath-live-eval-"))
    import logging

    import structlog

    # The recorder captures every provider error itself; keep the console readable (harness setup deliberately refuses the LLM).
    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.ERROR))


def require_live(settings) -> dict[str, bool]:
    """Names only -- no values. Live mode must be *real*: a disabled LLM provider is a configuration error."""
    present = {
        "LLM_API_KEY": bool(settings.llm_api_key), "HF_TOKEN": bool(settings.hf_token),
        "TAVILY_API_KEY": bool(settings.tavily_api_key), "GITHUB_TOKEN": bool(settings.github_token),
    }
    if settings.llm_provider == "none":
        raise LiveConfigError("live mode needs LLM_PROVIDER != none (see backend/.env); refusing to report an offline run as live")
    if settings.llm_provider in ("groq", "anthropic") and not settings.llm_api_key:
        raise LiveConfigError(f"LLM_PROVIDER={settings.llm_provider} but LLM_API_KEY is not set")
    if not (settings.llm_small_model and settings.llm_mid_model and settings.llm_strong_model):
        raise LiveConfigError("LLM_SMALL_MODEL / LLM_MID_MODEL / LLM_STRONG_MODEL must all be set")
    return present


def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=BACKEND_ROOT, capture_output=True, text=True, timeout=15).stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


def build_meta(settings, credentials: dict[str, bool], mode: str, suite: str, graph_version: str, test_count: int) -> dict[str, Any]:
    from app.assessment.prompting import BLIND_SOLVER_SYSTEM_PROMPT, GENERATION_SYSTEM_PROMPT
    from app.planning.prompting import PLANNER_SYSTEM_PROMPT
    from app.profiling.claim_extraction import EXTRACTION_SYSTEM_PROMPT
    from app.reflection.prompting import REFLECTION_SYSTEM_PROMPT
    from app.tutor.prompting import TUTOR_SYSTEM_PROMPT
    from tests.evaluation.live.scenarios import GOLD_LIVE

    def h(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:10]

    gold_dir = GOLD_LIVE.parent.parent / "gold"
    gold_hash = hashlib.sha256(b"".join(p.read_bytes() for p in sorted([*gold_dir.glob("*.json"), GOLD_LIVE]))).hexdigest()[:12]
    return {
        "mode": mode, "suite": suite, "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git_commit": _git("rev-parse", "--short", "HEAD") or "unknown",
        "git_dirty": bool(_git("status", "--porcelain")), "python": f"python {sys.version.split()[0]}",
        "providers": {
            "llm_provider": settings.llm_provider, "llm_small_model": settings.llm_small_model, "llm_mid_model": settings.llm_mid_model,
            "llm_strong_model": settings.llm_strong_model, "llm_timeout_s": settings.llm_timeout_s,
            "embedding_provider": settings.embedding_provider, "embedding_model": settings.embedding_model,
            "vlm_provider": settings.vlm_provider, "vlm_model": settings.vlm_model, "web_search_provider": settings.web_search_provider,
        },
        "credentials_present": credentials,
        "dataset": {"graph_version": graph_version, "gold_hash": gold_hash, "gold_live_version": "live-eval-gold-1"},
        "prompt_versions": {  # short content hashes of each agent's system prompt: no version constants exist in the repo
            "profiler": h(EXTRACTION_SYSTEM_PROMPT), "planner": h(PLANNER_SYSTEM_PROMPT), "assessor": h(GENERATION_SYSTEM_PROMPT + BLIND_SOLVER_SYSTEM_PROMPT),
            "reflection": h(REFLECTION_SYSTEM_PROMPT), "tutor": h(TUTOR_SYSTEM_PROMPT),
        },
        "deterministic_regression_test_count": test_count,
    }


def _json_default(o: Any) -> Any:
    if isinstance(o, (set, frozenset)):
        return sorted(o)
    return str(o)


async def _bootstrap(recorder) -> tuple[Any, Any, dict, dict, dict, list]:
    """Create the schema, ingest the curated catalog (embedding it with the LIVE embedding provider), load the graph."""
    from sqlalchemy import select

    from app.catalog.ingest import run_ingestion
    from app.db import models as m
    from app.db.base import Base
    from app.db.session import SessionLocal, engine
    from app.graph.loader import GraphLoader
    from app.graph.queries import SkillGraphService
    from app.main import app
    from app.repositories.catalog_repository import CatalogRepository
    from tests.evaluation.live.instrument import CaseContext, case_scope

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    ctx = CaseContext("bootstrap", "bootstrap")
    with case_scope(ctx):
        async with SessionLocal() as session:
            await run_ingestion(session)
        async with SessionLocal() as session:
            graph = SkillGraphService(await GraphLoader(CatalogRepository(session)).load())
            resources = {r.resource_id: r for r in (await session.execute(select(m.Resource))).scalars().all()}
            targets: dict[str, set[str]] = {}
            for rs in (await session.execute(select(m.ResourceSkill))).scalars().all():
                targets.setdefault(rs.resource_id, set()).add(rs.skill_id)
            skills = {s.skill_id: s for s in await CatalogRepository(session).get_all_skills()}
            misconceptions = list((await session.execute(select(m.Misconception))).scalars().all())
    return app, graph, resources, targets, skills, misconceptions


def _pick(spec: Any, items: list[Any]) -> list[Any]:
    return items if spec == "all" else items[: int(spec)] if isinstance(spec, int) else [i for i in items if i in spec]


async def run_evaluation(suite: str, areas: set[str] | None, min_interval_s: float, log: Callable[[str], None], tpm_budget: float = 0.0) -> dict[str, Any]:
    from app.config import get_settings
    from tests.evaluation.live import scenarios as sc
    from tests.evaluation.live.instrument import CaseContext, Recorder, TRANSIENT_CATEGORIES, case_scope, redact, register_secrets, summarize_llm_calls
    from tests.evaluation.live.report import (
        AREA_ORDER, offline_reference, quality_metrics, technical_metrics,
    )
    from tests.evaluation.metrics import load_gold

    settings = get_settings()
    credentials = require_live(settings)
    register_secrets(settings.llm_api_key, settings.hf_token, settings.tavily_api_key, settings.github_token, settings.session_secret)
    recorder = Recorder().install()
    started_at = time.perf_counter()
    try:
        app, graph, resources, targets, skills, misconceptions = await _bootstrap(recorder)
        gold_live = sc.load_live_gold()
        cfg = gold_live["suites"][suite]
        st = sc.EvalState(suite=suite, app=app, graph=graph, resources=resources, resource_targets=targets, skills=skills,
                          misconceptions=misconceptions, gold=gold_live, resource_count_at_start=len(resources))
        log(f"bootstrapped catalog: {len(skills)} skills, {len(resources)} resources, graph {graph.graph_version if hasattr(graph, 'graph_version') else '?'}")
        emb = [p for p in recorder.provider_calls if p.provider == "embeddings"]
        log(f"embedding requests during catalog ingestion: {len(emb)} ({sum(p.fell_back for p in emb)} fell back to deterministic)")

        resumes_all = load_gold("resumes.json")
        resumes = [r for r in resumes_all if cfg["resumes"] == "all" or r["id"] in cfg["resumes"]]
        personas = [p for p in gold_live["personas"] if cfg["personas"] == "all" or p["id"] in cfg["personas"]]
        refl_cases = await sc.reflection_cases(st)
        refl_cases = refl_cases if cfg["reflection_cases"] == "all" else refl_cases[: int(cfg["reflection_cases"])]
        assess_skills = sorted({m.skill_id for m in misconceptions})[: int(cfg["assessor_skills"])]
        qs = [q for q in gold_live["tutor_questions"] if cfg["tutor_questions"] == "all" or q["id"] in cfg["tutor_questions"]]

        plan: list[tuple[str, str, Callable[..., Awaitable[sc.CaseOutcome]], Any]] = []
        plan += [("profiling", f"profile-{r['id']}", sc.case_profiling, r) for r in resumes]
        plan += [("gap", f"gap-{r['id']}", sc.case_gap, r["id"]) for r in resumes]
        plan += [("planner", f"plan-{p['id']}", sc.case_planner, p) for p in personas]
        plan += [("assessor", f"assess-{s}", sc.case_assessor, s) for s in assess_skills]
        plan += [("reflection", f"reflect-{mc.misconception_id}", sc.case_reflection, (mc, picks)) for mc, picks in refl_cases]
        plan += [("tutor", f"tutor-{q['id']}", sc.case_tutor, q) for q in qs]
        plan += [("web", f"web-{s}", sc.case_web, s) for s in cfg["web_skills"]]
        plan += [("web", "web-plan-exclusion", sc.case_web_plan_exclusion, None)]
        if cfg.get("vision"):
            plan += [("vision", "vision-first-page-only", sc.case_vision, None)]
        plan += [("known_issues", "auth-cookie-forgeable", sc.case_auth_probe, None)]
        if areas:
            plan = [p for p in plan if p[0] in areas]

        cases: list[dict[str, Any]] = []
        throttle_events: list[dict[str, Any]] = []
        consecutive_throttled = breaker_trips = 0
        aborted = False
        queue: deque = deque((area, case_id, fn, spec, 1) for area, case_id, fn, spec in plan)
        done = 0
        total = len(plan)
        while queue:
            area, case_id, fn, spec, attempt = queue.popleft()
            base = {"area": area, "case_id": case_id}
            if aborted and area in AREAS_LLM:
                cases.append({**base, "status": "skipped", "skip_reason": "aborted: the provider stayed rate-limited after repeated cooldowns", "latency_ms": 0.0,
                              "llm_calls": 0, "llm_degraded": 0, "gateway_retries": 0, "agent_retries": 0, "attempts": 0, "fallback": None, "schema_valid": None,
                              "validator_pass": None, "metrics": {}, "checks": {}, "failed_checks": [], "examples": [], "notes": [], "error": None, "throttled": False})
                done += 1
                log(f"[{done}/{total}] {case_id}: skipped (aborted)")
                continue
            ctx = CaseContext(area, case_id)
            t0 = time.perf_counter()
            error: str | None = None
            outcome = sc.CaseOutcome()
            with case_scope(ctx):
                try:
                    outcome = await fn(st, ctx, spec)
                except Exception as exc:  # noqa: BLE001 -- a case reports, it never crashes the run
                    error = f"{type(exc).__name__}: {redact(str(exc), 200)}"
            latency = (time.perf_counter() - t0) * 1000
            counted = [c for c in ctx.llm_calls if not c.setup]
            degraded = [c for c in counted if c.degraded]
            cats = {a.error_category for c in counted for a in c.attempts if a.error_category}
            throttled = "rate_limit" in cats
            failed_checks = [k for k, v in outcome.checks.items() if not v]
            reasons = sorted({c.error_category or "degraded" for c in degraded})
            transient = bool(degraded) and {c.error_category for c in degraded} <= TRANSIENT_CATEGORIES
            if error is not None:
                status = "provider_error" if transient else "fail"
            elif failed_checks:
                status = "fail"
            elif transient:
                status = "provider_error"
            elif outcome.fallback or degraded:
                status = "fallback"
            else:
                status = "pass"
            if status == "provider_error" and attempt == 1 and area in AREAS_LLM:
                # One re-run after a cooldown, so a throttled minute does not erase a case. The first attempt's calls stay
                # in the call statistics (the throttling is itself a measurement); only the final attempt is the case result.
                throttle_events.append({"case_id": case_id, "reasons": reasons, "llm_calls": len(counted), "latency_ms": round(latency, 1)})
                log(f"{case_id}: provider error ({', '.join(reasons)}) -> cooling down 75s, then one re-run")
                await asyncio.sleep(75.0)
                consecutive_throttled = 0
                queue.append((area, case_id, fn, spec, 2))
                continue
            case = {
                **base, "status": status, "skip_reason": None, "latency_ms": round(latency, 1), "llm_calls": len(counted), "llm_degraded": len(degraded),
                "gateway_retries": sum(c.gateway_retries for c in counted), "agent_retries": ctx.agent_retries,
                "attempts": sum(len(c.attempts) for c in counted), "fallback": outcome.fallback, "schema_valid": outcome.schema_valid,
                "validator_pass": outcome.validator_pass, "metrics": outcome.metrics, "checks": outcome.checks, "failed_checks": failed_checks,
                "examples": outcome.examples, "notes": outcome.notes, "error": error, "throttled": throttled, "degraded_reasons": reasons,
                "first_attempt_provider_error": attempt == 2, "provider_calls": [p.as_dict() for p in ctx.provider_calls],
            }
            cases.append(case)
            done += 1
            log(f"[{done}/{total}] {case_id}: {status} ({latency / 1000:.1f}s, {len(counted)} llm calls{', ' + error if error else ''}{', failed: ' + ','.join(failed_checks) if failed_checks else ''})")
            if area in AREAS_LLM:
                consecutive_throttled = consecutive_throttled + 1 if throttled and degraded else 0
                if consecutive_throttled >= 2:
                    breaker_trips += 1
                    consecutive_throttled = 0
                    if breaker_trips >= 3:
                        aborted = True
                        log("circuit breaker: rate-limited after 3 cooldowns -> remaining LLM cases are skipped (provider quota, not model quality)")
                    else:
                        log(f"circuit breaker trip {breaker_trips}: 2 consecutive rate-limited cases -> cooling down 75s")
                        await asyncio.sleep(75.0)
                elif throttled:
                    await asyncio.sleep(20.0)  # let a per-minute quota window drain
                elif counted:
                    # token-aware pacing: spread a case's tokens over the per-minute budget (0 disables), never below min_interval
                    tokens = sum(c.tokens_in + c.tokens_out for c in counted)
                    pace = (tokens / tpm_budget * 60.0 - latency / 1000.0) if tpm_budget else 0.0
                    await asyncio.sleep(max(min_interval_s, pace))

        llm_calls = [c.as_dict() for c in recorder.llm_calls if not c.setup]
        provider_calls = [p.as_dict() for p in recorder.provider_calls]
        by_area: dict[str, list[dict[str, Any]]] = {}
        for c in cases:
            by_area.setdefault(c["area"], []).append(c)
        cases_by_area = {a: by_area[a] for a in AREA_ORDER if a in by_area}
        test_count = int(os.environ.get("EVAL_OFFLINE_TEST_COUNT", "0") or 0)
        report = {
            "meta": build_meta(settings, credentials, "live", suite, getattr(graph, "graph_version", "unknown"), test_count),
            "technical": technical_metrics(cases, llm_calls, provider_calls),
            "llm_summary": summarize_llm_calls([c for c in recorder.llm_calls]),
            "quality": quality_metrics(cases_by_area),
            "cases": cases, "cases_by_area": cases_by_area, "throttle_events": throttle_events, "breaker_trips": breaker_trips, "llm_calls": llm_calls, "provider_calls": provider_calls,
            "offline_reference": offline_reference(BACKEND_ROOT / "reports"),
            "wall_time_s": round(time.perf_counter() - started_at, 1),
        }
        report["meta"]["cases_planned"] = len(plan)
        report["meta"]["pacing"] = {"min_interval_s": min_interval_s, "tpm_budget": tpm_budget, "cooldown_s": 75, "rerun_after_cooldown": 1, "breaker_trips_before_abort": 3}
        return report
    finally:
        recorder.uninstall()


def run_offline(log: Callable[[str], None]) -> int:
    """Offline mode == the existing deterministic evaluation suite, unchanged (providers pinned to none by
    tests/conftest.py). It writes reports/evaluation_metrics.{json,md} exactly as before."""
    log("offline mode: running the existing deterministic evaluation suite (tests/evaluation)")
    proc = subprocess.run([sys.executable, "-m", "pytest", "tests/evaluation", "-q"], cwd=BACKEND_ROOT)
    return proc.returncode


_MEASURED_RANK = {"pass": 3, "fallback": 3, "fail": 3, "provider_error": 1, "skipped": 0}


def merge_reports(reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Combine several live runs (e.g. a run cut short by a provider quota + a later re-run of the missing areas) into one
    report, recomputing every aggregate with the CURRENT code. Per case the best-measured result wins (pass/fallback/fail
    beat provider_error beat skipped; the earlier run wins ties) and every case keeps `source_run`. Calls are kept only
    for the chosen results, so no case is double counted. Nothing is invented: a case nobody measured stays skipped."""
    from tests.evaluation.live.report import AREA_ORDER, offline_reference, quality_metrics, technical_metrics

    def tag(rep: dict[str, Any]) -> str:
        return f"{rep['meta']['timestamp_utc']}/{rep['meta']['suite']}"

    chosen: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for rep in reports:
        for c in rep["cases"]:
            c = {**c, "source_run": tag(rep)}
            cur = chosen.get(c["case_id"])
            if cur is None:
                order.append(c["case_id"])
                chosen[c["case_id"]] = c
            elif _MEASURED_RANK[c["status"]] > _MEASURED_RANK[cur["status"]]:
                chosen[c["case_id"]] = c
    cases = [chosen[i] for i in order]
    for c in cases:  # reports written before the Assessor's validator_pass was redefined to "blind solver accepted every item"
        m = c.get("metrics") or {}
        if c["area"] == "assessor" and "blind_solver_n" in m:
            c["validator_pass"] = m["blind_solver_n"] > 0 and m["blind_solver_agree"] == m["blind_solver_n"]
    keep = {(c["case_id"], c["source_run"]) for c in cases}
    llm_calls, provider_calls, throttle = [], [], []
    for rep in reports:
        t = tag(rep)
        llm_calls += [{**c, "source_run": t} for c in rep["llm_calls"] if (c["operation"], t) in keep or c["operation"] == "bootstrap"]
        provider_calls += [{**p, "source_run": t} for p in rep["provider_calls"] if (p["operation"], t) in keep or (p["operation"] == "bootstrap" and rep is reports[0])]
        throttle += [{**e, "source_run": t} for e in rep.get("throttle_events", [])]
    by_area: dict[str, list[dict[str, Any]]] = {}
    for c in cases:
        by_area.setdefault(c["area"], []).append(c)
    cases_by_area = {a: by_area[a] for a in AREA_ORDER if a in by_area}
    meta = {**reports[0]["meta"], "suite": "full (merged)", "merged_from": [tag(r) for r in reports],
            "merge_note": "per case, the best-measured result across the listed runs; each case carries source_run"}
    return {
        "meta": meta, "technical": technical_metrics(cases, llm_calls, provider_calls), "quality": quality_metrics(cases_by_area),
        "cases": cases, "cases_by_area": cases_by_area, "llm_calls": llm_calls, "provider_calls": provider_calls, "throttle_events": throttle,
        "offline_reference": offline_reference(BACKEND_ROOT / "reports"),
    }
