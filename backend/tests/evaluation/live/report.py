"""Aggregation + rendering of live-evaluation results (JSON and Markdown).

Rules of the house:
  * a metric that cannot be measured is `None` and renders as "N/A" -- never 0, never guessed;
  * quality metrics are micro-averaged over the cases that actually ran (so a skipped/aborted case cannot
    silently improve a rate);
  * nothing here calls a model.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tests.evaluation.live.instrument import mean, percentile

NA = "N/A (not scored)"
AREA_ORDER = ["profiling", "gap", "planner", "assessor", "reflection", "tutor", "web", "vision", "known_issues"]
AREA_TITLE = {
    "profiling": "A. Profiling", "gap": "B. Gap analysis", "planner": "C. Planner", "assessor": "D. Assessment",
    "reflection": "E. Reflection", "tutor": "F. Tutor", "web": "G. Web search", "vision": "H. Vision (known limitation probe)",
    "known_issues": "I. Known-issue probes",
}


def _r(v: float | None, d: int = 3) -> float | None:
    return None if v is None else round(v, d)


def _rate(num: float, den: float) -> float | None:
    return None if not den else num / den


def _fmt(v: Any) -> str:
    if v is None:
        return "N/A"
    if isinstance(v, float):
        return f"{v:.0f}" if abs(v) >= 100 else f"{v:.3f}"
    return str(v)


# --------------------------------------------------------------------------------------------------------------------
# technical metrics


def technical_metrics(cases: list[dict[str, Any]], llm_calls: list[dict[str, Any]], provider_calls: list[dict[str, Any]]) -> dict[str, Any]:
    ran = [c for c in cases if c["status"] != "skipped"]
    behaviour = [c for c in ran if c["status"] != "provider_error"]  # a 429 says nothing about the model's output quality
    llm_cases = [c for c in behaviour if c["llm_calls"] > 0]
    lat_calls = [c["latency_ms"] for c in llm_calls if not c["degraded"]]
    lat_cases = [c["latency_ms"] for c in ran if c["llm_calls"] > 0 and c["status"] in ("pass", "fallback")]
    retries = sum(c["attempts"] - 1 for c in llm_calls if c["attempts"] > 1)
    schema = [c["schema_valid"] for c in behaviour if c["schema_valid"] is not None]
    validator = [c["validator_pass"] for c in behaviour if c["validator_pass"] is not None]
    fb = [c for c in llm_cases if c["fallback"] is not None]
    errors: dict[str, int] = {}
    for call in llm_calls:
        for cat in call["attempt_errors"]:
            errors[cat] = errors.get(cat, 0) + 1
    perr: dict[str, dict[str, int]] = {}
    for p in provider_calls:
        if not p["ok"]:
            perr.setdefault(p["provider"], {})
            perr[p["provider"]][p["error_category"] or "error"] = perr[p["provider"]].get(p["error_category"] or "error", 0) + 1
    status_counts: dict[str, int] = {}
    for c in cases:
        status_counts[c["status"]] = status_counts.get(c["status"], 0) + 1
    return {
        "total_cases": len(cases),
        "successful_cases": status_counts.get("pass", 0),
        "fallback_cases": status_counts.get("fallback", 0),
        "failed_cases": status_counts.get("fail", 0),
        "provider_error_cases": status_counts.get("provider_error", 0),
        "skipped_cases": status_counts.get("skipped", 0),
        "schema_valid_rate": _r(_rate(sum(schema), len(schema))),
        "schema_valid_n": len(schema),
        "validator_pass_rate": _r(_rate(sum(validator), len(validator))),
        "validator_pass_n": len(validator),
        "fallback_rate": _r(_rate(sum(bool(c["fallback"]) or c["llm_degraded"] > 0 for c in fb), len(fb))),
        "fallback_rate_n": len(fb),
        "llm_calls": len(llm_calls),
        "llm_calls_degraded": sum(c["degraded"] for c in llm_calls),
        "gateway_retries": retries,
        "agent_schema_retries": sum(c["agent_retries"] for c in ran),
        "retry_rate_per_call": _r(_rate(retries + sum(c["agent_retries"] for c in ran), len(llm_calls))),
        "calls_needing_retry_rate": _r(_rate(sum(c["attempts"] > 1 for c in llm_calls), len(llm_calls))),
        "llm_call_latency_ms": {"avg": _r(mean(lat_calls), 0), "p50": _r(percentile(lat_calls, 50), 0), "p95": _r(percentile(lat_calls, 95), 0),
                                 "max": _r(max(lat_calls) if lat_calls else None, 0), "n": len(lat_calls)},
        "case_latency_ms": {"avg": _r(mean(lat_cases), 0), "p50": _r(percentile(lat_cases, 50), 0), "p95": _r(percentile(lat_cases, 95), 0), "n": len(lat_cases)},
        "provider_errors": {"llm_attempt_errors_by_category": errors, "non_llm_provider_errors": perr},
        "tokens_in": sum(c["tokens_in"] for c in llm_calls), "tokens_out": sum(c["tokens_out"] for c in llm_calls),
    }


# --------------------------------------------------------------------------------------------------------------------
# quality metrics, per area


def _m(cases: list[dict[str, Any]], key: str) -> list[Any]:
    return [c["metrics"][key] for c in cases if key in c["metrics"] and c["metrics"][key] is not None]


def _sum(cases: list[dict[str, Any]], key: str) -> float:
    return sum(v for v in _m(cases, key) if isinstance(v, (int, float)) and not isinstance(v, bool))


def _check_rate(cases: list[dict[str, Any]], check: str) -> float | None:
    vals = [c["checks"][check] for c in cases if check in c["checks"]]
    return _rate(sum(vals), len(vals))


def quality_metrics(cases_by_area: dict[str, list[dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    q: dict[str, dict[str, Any]] = {}

    def put(area: str, name: str, value: Any, n: int | None = None, note: str = "") -> None:
        q.setdefault(area, {})[name] = {"value": _r(value) if isinstance(value, float) else value, "n": n, "note": note}

    def na(area: str, name: str, why: str) -> None:
        q.setdefault(area, {})[name] = {"value": None, "n": 0, "note": f"{NA}: {why}"}

    def ran(area: str) -> list[dict[str, Any]]:
        return [c for c in cases_by_area.get(area, []) if c["status"] not in ("skipped", "provider_error") and c["metrics"]]

    # -- A profiling
    a = ran("profiling")
    if a:
        tp, fp, fn = _sum(a, "tp"), _sum(a, "fp"), _sum(a, "fn")
        p, r = _rate(tp, tp + fp), _rate(tp, tp + fn)
        put("profiling", "skill precision (micro)", p, len(a), f"tp={tp:.0f} fp={fp:.0f}")
        put("profiling", "skill recall (micro)", r, len(a), f"tp={tp:.0f} fn={fn:.0f}")
        put("profiling", "skill F1", _rate(2 * p * r, p + r) if p and r else None, len(a), "skill identification accuracy vs gold")
        put("profiling", "forbidden-skill hits (injection / negatives)", int(_sum(a, "forbidden_hits")), len(a), "must be 0")
        put("profiling", "unsupported-claim rate (span does not contain skill label/alias)", _rate(_sum(a, "unsupported_claims"), _sum(a, "mapped_claims")), len(a), "heuristic literal check")
        put("profiling", "LLM claims dropped by span verification (fabricated/unverifiable)", _rate(_sum(a, "dropped_unverified"), _sum(a, "extracted")), len(a), "hallucinated-span rate")
        put("profiling", "prompt-injection claims dropped", int(_sum(a, "dropped_injection")), len(a), "")
        put("profiling", "quoted span present in source document", _rate(_sum(a, "span_present_ok"), _sum(a, "claims")), len(a), "hard invariant (Evidence Verifier)")
        put("profiling", "exact character offsets (scrubbed[start:end] == span)", _rate(_sum(a, "span_fidelity_ok"), _sum(a, "claims")), len(a), "verifier accepts >= 0.9 similarity, so live-LLM offsets may drift")
        put("profiling", "first-try schema-valid rate", _rate(sum(bool(v) for v in _m(a, "first_try_schema_valid")), len(_m(a, "first_try_schema_valid"))), len(a), "no agent retry needed")
        right = [x for c in a for x in c["metrics"].get("conf_right", [])]
        wrong = [x for c in a for x in c["metrics"].get("conf_wrong", [])]
        put("profiling", "normalization confidence: correct vs incorrect skills", f"{_fmt(_r(mean(right)))} vs {_fmt(_r(mean(wrong)))}", len(right) + len(wrong), "calibration hint: correct should exceed incorrect")
        tiers: dict[str, int] = {}
        for c in a:
            for k, v in c["metrics"].get("tiers", {}).items():
                tiers[k] = tiers.get(k, 0) + v
        put("profiling", "evidence-tier distribution (E0/E1)", json.dumps(tiers, sort_keys=True), sum(tiers.values()), "")
        na("profiling", "evidence-tier assignment accuracy", "no gold tier labels; only the invariant 'resume alone never above E1' is checked")
        put("profiling", "resume-alone-never-above-E1 invariant", _check_rate(a, "resume_alone_never_above_E1"), len(a), "")

    # -- B gap
    g = ran("gap")
    if g:
        put("gap", "status agreement, live-profiled vs gold-profiled learner", _rate(_sum(g, "status_agree"), _sum(g, "status_pairs")), len(g), "tier held at E1; isolates skill-identification error")
        put("gap", "missing-vs-known agreement", _rate(_sum(g, "coverage_agree"), _sum(g, "coverage_pairs")), len(g), "")
        put("gap", "gap-set Jaccard (micro)", _rate(_sum(g, "gap_intersection"), _sum(g, "gap_union")), len(g), "non-MET skill sets")
        put("gap", "top-5 priority overlap", _rate(_sum(g, "top5_overlap"), _sum(g, "top5_n")), len(g), "prioritization")
        put("gap", "prerequisite ordering consistency", _check_rate(g, "prerequisite_consistency"), len(g), "API report")
        put("gap", "verify-before-teach objective typing", _check_rate(g, "verify_before_teach"), len(g), "")
        na("gap", "required-skill / skill-level accuracy vs an independent gold", "the engine is deterministic and verified against an oracle in the offline suite (tests/evaluation); no LLM output to score")

    # -- C planner
    p = ran("planner")
    if p:
        put("planner", "final plan validity (all hard checks)", _rate(sum(all(c["checks"].values()) for c in p), len(p)), len(p), "budget, referential integrity, alignment, order, non-empty")
        put("planner", "LLM draft accepted by validator on first attempt", _rate(sum(bool(v) for v in _m(p, "first_attempt_pass")), len(p)), len(p), "")
        put("planner", "fallback-planner rate", _rate(sum(bool(c["fallback"]) for c in p), len(p)), len(p), "deterministic planner replaced the LLM plan")
        put("planner", "validator rejections (drafts)", int(_sum(p, "validator_rejections")), len(p), "")
        put("planner", "objective coverage (all objectives)", _rate(_sum(p, "objectives_covered"), _sum(p, "objectives_total")), len(p), "budget-limited by design")
        put("planner", "objective coverage (top-10 by priority)", _rate(_sum(p, "top10_covered"), _sum(p, "top10_total")), len(p), "")
        put("planner", "prerequisite ordering", _check_rate(p, "prerequisite_order"), len(p), "")
        put("planner", "resource/skill alignment (TARGETS edge exists)", _rate(_sum(p, "aligned_resources"), _sum(p, "items_with_resource")), len(p), "")
        put("planner", "time-budget adherence (<= budget)", _check_rate(p, "within_time_budget"), len(p), "")
        put("planner", "unsupported resources scheduled", int(sum(not c["checks"].get("every_resource_exists_and_is_healthy", True) for c in p)), len(p), "must be 0")
        put("planner", "items with a reason text", _rate(_sum(p, "items_with_reason_text"), _sum(p, "items")), len(p), "LLM-phrased, display only")
        put("planner", "items with ID provenance (graph_path / evidence_ids / decision_id)", _rate(_sum(p, "items_with_id_provenance"), _sum(p, "items")), len(p), "design 16.6 says IDs are attached deterministically")
        put("planner", "mean budget utilization", _rate(sum(_m(p, "utilization")), len(_m(p, "utilization"))), len(p), "of hours*60 (Stage 1 baseline: 0.219); Stage 2 sessionization targets acceptable, not maximal, use")
        put("planner", "mean utilization of the planner's own (0.9-slack) budget", _rate(sum(_m(p, "utilization_effective")), len(_m(p, "utilization_effective"))), len(p), "")
        put("planner", "resource items with session provenance", _rate(_sum(p, "items_with_session"), _sum(p, "items_with_resource")), len(p), "Stage 2: must be 1.0")
        put("planner", "sessions matching the catalog-derived session (problems)", int(_sum(p, "session_problems")), len(p), "recomputed from the raw catalog row; must be 0")
        put("planner", "duplicate sessions / resources over-consumed", int(_sum(p, "duplicate_sessions") + _sum(p, "resources_over_consumed")), len(p), "must be 0")
        put("planner", "minutes added by the deterministic top-up (share of scheduled)", _rate(_sum(p, "topup_min"), _sum(p, "scheduled_min")), len(p), "the rest was selected by the model (or the fallback planner)")
        put("planner", "distinct resources per plan (mean)", _rate(_sum(p, "distinct_resources"), len(p)), len(p), "")
        put("planner", "plans under-filled (< 50% of budget)", _rate(sum(bool(v) for v in _m(p, "under_filled_50pct")), len(p)), len(p), "")
        put("planner", "coherence: overall reason present, no duplicate items", _rate(sum(bool(c["metrics"].get("overall_reason_present")) and c["metrics"].get("duplicate_items", 1) == 0 for c in p), len(p)), len(p), "deterministic proxy; no LLM judge")

    # -- D assessor
    d = ran("assessor")
    if d:
        put("assessor", "item generation succeeded (>= 1 valid item)", _rate(sum(c["metrics"]["generated"] > 0 for c in d), len(d)), len(d), "")
        put("assessor", "items generated / requested", _rate(_sum(d, "generated"), _sum(d, "requested")), len(d), "")
        put("assessor", "first-try schema-valid rate", _rate(sum(bool(v) for v in _m(d, "first_try_schema_valid")), len(d)), len(d), "")
        put("assessor", "deterministic rubric pass rate", _rate(_sum(d, "rubric_checks_passed"), _sum(d, "rubric_checks_total")), len(d), "10 checks per item (see per-check table)")
        put("assessor", "blind-solver agreement (MODEL-BASED, small tier; not ground truth)", _rate(_sum(d, "blind_solver_agree"), _sum(d, "blind_solver_n")), len(d), "key correctness proxy")
        put("assessor", "distractor misconception-tag coverage", _rate(_sum(d, "distractors_tagged"), _sum(d, "distractors")), len(d), "share of distractors tagged")
        put("assessor", "misconception-tag validity (only catalogued ids)", _check_rate(d, "tags_only_from_catalogue"), len(d), "")
        put("assessor", "distinct stems within a batch", _rate(_sum(d, "distinct_stems"), _sum(d, "generated")), len(d), "")
        na("assessor", "key-correctness / distractor-plausibility vs gold", "no gold-labelled generated items; blind solver is the only (model-based) signal")
        na("assessor", "misconception-tag *correctness* (right misconception for the distractor)", "no gold labels for generated distractors")
        agg: dict[str, list[int]] = {}
        for c in d:
            for k, v in c["metrics"].get("per_check", {}).items():
                agg.setdefault(k, [0, 0])
                agg[k][0] += v
                agg[k][1] += c["metrics"]["generated"]
        put("assessor", "per-check rubric pass counts", json.dumps({k: f"{v[0]}/{v[1]}" for k, v in sorted(agg.items())}), sum(v[1] for v in agg.values()), "")

    # -- E reflection
    e = ran("reflection")
    if e:
        put("reflection", "root-cause skill correct (== injected)", _rate(sum(bool(v) for v in _m(e, "root_correct")), len(e)), len(e), "gold: curated misconception -> root skill")
        put("reflection", "misconception identified correctly", _rate(sum(bool(v) for v in _m(e, "misconception_correct")), len(e)), len(e), "gold: injected misconception id")
        put("reflection", "root cause graph-connected to struggling skill", _check_rate(e, "root_cause_is_graph_connected"), len(e), "")
        put("reflection", "operators within the closed set", _check_rate(e, "operators_in_closed_set"), len(e), "")
        put("reflection", "plan-edit validity (committed + decision recorded)", _check_rate(e, "revision_committed_with_decision"), len(e), "")
        put("reflection", "revised plan references real resources", _check_rate(e, "revised_plan_references_real_resources"), len(e), "")
        put("reflection", "evidence grounding (decision cites known signals/assessments)", _rate(_sum(e, "evidence_known"), _sum(e, "evidence_ids")), len(e), "")
        put("reflection", "remediation resources catalogued for the misconception", _rate(_sum(e, "remediation_grounded"), _sum(e, "remediation_resources")), len(e), "")
        put("reflection", "LLM path used (no deterministic-policy fallback)", _rate(sum(not c["fallback"] for c in e), len(e)), len(e), "")
        put("reflection", "learner explanation names the concept (root/struggling skill or misconception topic)", _rate(sum(bool(v) for v in _m(e, "explanation_names_concept")), len(e)), len(e), "coarse keyword check")

    # -- F tutor
    t = ran("tutor")
    if t:
        put("tutor", "final citations real & learner-scoped", _check_rate(t, "final_citations_are_real_and_learner_scoped"), len(t), "code-enforced; must be 1.0")
        cited = sum(c["metrics"]["citations"] for c in t)
        put("tutor", "unsupported-citation rate (first draft rejected by verifier)", _rate(sum(bool(c["metrics"]["first_draft_rejected"]) for c in t), len(t)), len(t), "the verifier then forces a regeneration or conservative answer")
        put("tutor", "adversary-supplied ids never cited", _check_rate(t, "no_adversary_supplied_id_cited"), len(t), "")
        exp_met, exp_tot = _sum(t, "expectations_met"), _sum(t, "expectations_total")
        put("tutor", "gold expectations met (cited ids / keywords)", _rate(exp_met, exp_tot), len(t), "coarse rubric; not exact-answer accuracy")
        ins = [c for c in t if c["metrics"].get("in_scope")]
        put("tutor", "in-scope answers with >= 1 citation", _rate(sum(c["metrics"]["citations"] > 0 for c in ins), len(ins)), len(ins), "")
        oos = [c for c in t if c["metrics"].get("kind") == "oos"]
        put("tutor", "out-of-scope questions refused (no citations or conservative)", _rate(sum(bool(c["metrics"]["refused_or_conservative"]) for c in oos), len(oos)), len(oos), "")
        put("tutor", "conservative (non-LLM) answers", _rate(sum(bool(c["metrics"]["conservative"]) for c in t), len(t)), len(t), "")
        put("tutor", "ids named in answer text that do not exist", int(_sum(t, "unreal_ids_in_text")), len(t), "")
        put("tutor", "response latency p50 / p95 (ms)", f"{_fmt(_r(percentile([c['latency_ms'] for c in t], 50), 0))} / {_fmt(_r(percentile([c['latency_ms'] for c in t], 95), 0))}", len(t), "whole /chat request")
        na("tutor", "free-text answer correctness", "no gold answers; only cited-id / keyword expectations are scored")

    # -- G web
    w = ran("web")
    web = [c for c in w if "fetched" in c["metrics"]]
    if web:
        put("web", "search executed and returned results", _rate(sum(bool(c["metrics"]["fetched"]) and c["metrics"]["results"] > 0 for c in web), len(web)), len(web), "")
        put("web", "mean results per query", _rate(_sum(web, "results"), len(web)), len(web), "")
        put("web", "domain restriction (https + allowlist)", _check_rate(web, "all_https_and_allowlisted"), len(web), "")
        put("web", "all results marked unvetted", _check_rate(web, "all_marked_unvetted"), len(web), "")
        put("web", "no catalog id on web results / catalog untouched", _rate(sum(c["checks"].get("no_catalog_id_on_web_results", False) and c["checks"].get("catalog_not_mutated_by_search", False) for c in web), len(web)), len(web), "")
        put("web", "result relevance (title/url shares a skill keyword)", _rate(_sum(web, "relevant_by_keyword"), _sum(web, "results")), len(web), "keyword heuristic")
    ex = [c for c in cases_by_area.get("web", []) if c["case_id"] == "web-plan-exclusion" and c["status"] != "skipped"]
    if ex and ex[0]["metrics"].get("plans_checked"):
        put("web", "unvetted results excluded from plans", _check_rate(ex, "no_web_result_url_in_any_plan"), ex[0]["metrics"]["plans_checked"], "")
    elif ex:
        na("web", "unvetted results excluded from plans", "no plan was produced in this run (run the planner area too)")

    # -- H vision
    v = [c for c in cases_by_area.get("vision", []) if c["status"] in ("pass", "fallback", "provider_error") and c["metrics"]]  # VLM-side metrics stand even if the extraction LLM was throttled
    if v:
        put("vision", "VLM requests for a 2-page image-only PDF", v[0]["metrics"]["vlm_calls"], 1, "1 == only the first page is read")
        put("vision", "page-1 skill recall (image-only PDF)", v[0]["metrics"]["page1_recall"], 1, "")
        put("vision", "page-2 skill recall (image-only PDF)", v[0]["metrics"]["page2_recall"], 1, "KNOWN LIMITATION: only the first page is read")

    # -- I known issues
    k = ran("known_issues")
    for c in k:
        if "cookie_forgeable" in c["metrics"]:
            put("known_issues", "session cookie forgeable", c["metrics"]["cookie_forgeable"], 1, "KNOWN ISSUE (security): unsigned cookie")
    return q


def offline_reference(reports_dir: Path) -> dict[str, Any]:
    path = reports_dir / "evaluation_metrics.json"
    if not path.exists():
        return {}
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return {}
    return {f"{r['area']} | {r['metric']}": r["value"] for r in rows}


# --------------------------------------------------------------------------------------------------------------------
# markdown


def utilization_table(planner_cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for c in sorted((c for c in planner_cases if c["metrics"] and "utilization" in c["metrics"]), key=lambda c: c["metrics"]["hours"]):
        m = c["metrics"]
        rows.append({"case": c["case_id"], "hours": m["hours"], "scheduled_min": m["scheduled_min"], "budget_min": m["budget_min"],
                     "utilization": m["utilization"], "fallback": c["fallback"], "items": m["items"]})
    return rows


def render_markdown(report: dict[str, Any]) -> str:
    meta, tech, quality = report["meta"], report["technical"], report["quality"]
    lines: list[str] = []
    w = lines.append
    w(f"# EduPath live LLM evaluation — {meta['mode']} / {meta['suite']}")
    w("")
    w(f"*{meta['timestamp_utc']} · commit `{meta['git_commit']}`{' (dirty tree)' if meta['git_dirty'] else ''} · {meta['python']}*")
    w("")
    w("## Configuration")
    w("")
    w(f"- LLM: `{meta['providers']['llm_provider']}` — small `{meta['providers']['llm_small_model']}`, mid `{meta['providers']['llm_mid_model']}`, strong `{meta['providers']['llm_strong_model']}`")
    w(f"- Embeddings: `{meta['providers']['embedding_provider']}` / `{meta['providers']['embedding_model']}` · Vision: `{meta['providers']['vlm_provider']}` / `{meta['providers']['vlm_model']}` · Web: `{meta['providers']['web_search_provider']}`")
    w(f"- Credentials present (by name only): {', '.join(k for k, v in meta['credentials_present'].items() if v) or 'none'}")
    w(f"- Dataset: graph `{meta['dataset']['graph_version']}`, gold hash `{meta['dataset']['gold_hash']}` · prompts: " + ", ".join(f"{k} `{v}`" for k, v in meta["prompt_versions"].items()))
    w(f"- Determinism: temperature 0, but hosted models are **nondeterministic** across runs; treat single-run differences as noise (see LLM_EVALUATION.md).")
    w("")
    w("## Technical metrics")
    w("")
    w("| Metric | Value |")
    w("|---|---|")
    for label, key in [
        ("Total cases", "total_cases"), ("Successful (live path, all hard checks pass)", "successful_cases"),
        ("Completed on a deterministic fallback", "fallback_cases"), ("Failed (hard check violated / exception)", "failed_cases"),
        ("Not evaluable — provider error", "provider_error_cases"), ("Skipped / aborted", "skipped_cases"),
    ]:
        w(f"| {label} | {tech[key]} |")
    w(f"| Schema-valid rate | {_fmt(tech['schema_valid_rate'])} (n={tech['schema_valid_n']}) |")
    w(f"| Validator-pass rate (draft accepted without rejection) | {_fmt(tech['validator_pass_rate'])} (n={tech['validator_pass_n']}) |")
    w(f"| Fallback rate | {_fmt(tech['fallback_rate'])} (n={tech['fallback_rate_n']}) |")
    w(f"| Provider throttling: cases first hit by a provider error and retried once after cooldown | {len(report.get('throttle_events', []))} |")
    w(f"| LLM gateway calls / degraded | {tech['llm_calls']} / {tech['llm_calls_degraded']} |")
    w(f"| Retry rate (gateway + schema retries per call) | {_fmt(tech['retry_rate_per_call'])} (gateway retries {tech['gateway_retries']}, schema retries {tech['agent_schema_retries']}) |")
    lat = tech["llm_call_latency_ms"]
    w(f"| LLM call latency avg / p50 / p95 / max (ms) | {_fmt(lat['avg'])} / {_fmt(lat['p50'])} / {_fmt(lat['p95'])} / {_fmt(lat['max'])} (n={lat['n']}) |")
    cl = tech["case_latency_ms"]
    w(f"| LLM-bearing case latency avg / p50 / p95 (ms) | {_fmt(cl['avg'])} / {_fmt(cl['p50'])} / {_fmt(cl['p95'])} (n={cl['n']}) |")
    w(f"| Provider errors (LLM attempts, by category) | {json.dumps(tech['provider_errors']['llm_attempt_errors_by_category']) or '{}'} |")
    w(f"| Provider errors (embeddings/vision/web) | {json.dumps(tech['provider_errors']['non_llm_provider_errors']) or '{}'} |")
    w(f"| Tokens in / out | {tech['tokens_in']} / {tech['tokens_out']} |")
    w("")
    w("### Per area")
    w("")
    w("| Area | Cases | pass | fallback | fail | provider err | skipped | LLM calls | p50 case ms |")
    w("|---|---|---|---|---|---|---|---|---|")
    for area in AREA_ORDER:
        cs = report["cases_by_area"].get(area)
        if not cs:
            continue
        cnt = lambda s: sum(c["status"] == s for c in cs)  # noqa: E731
        lat_a = [c["latency_ms"] for c in cs if c["status"] != "skipped"]
        w(f"| {AREA_TITLE[area]} | {len(cs)} | {cnt('pass')} | {cnt('fallback')} | {cnt('fail')} | {cnt('provider_error')} | {cnt('skipped')} | {sum(c['llm_calls'] for c in cs)} | {_fmt(_r(percentile(lat_a, 50), 0))} |")
    w("")
    w("## Quality metrics")
    ref = report.get("offline_reference", {})
    for area in AREA_ORDER:
        rows = quality.get(area)
        if not rows:
            continue
        w("")
        w(f"### {AREA_TITLE[area]}")
        w("")
        w("| Metric | Live value | n | Note |")
        w("|---|---|---|---|")
        for name, row in rows.items():
            w(f"| {name} | {_fmt(row['value']) if row['value'] is not None else 'N/A'} | {row['n'] if row['n'] is not None else ''} | {row['note']} |")
        if area == "planner":
            w("")
            w("Budget utilization by weekly hours (thin-plan measurement; offline fallback baseline was 38% / 15% / 8% / 4% at 2/5/10/20 h):")
            w("")
            w("| Case | Hours | Scheduled min | Budget min | Utilization | Fallback |")
            w("|---|---|---|---|---|---|")
            for r in utilization_table(report["cases_by_area"].get("planner", [])):
                w(f"| {r['case']} | {r['hours']} | {r['scheduled_min']} | {r['budget_min']} | {r['utilization']:.0%} | {r['fallback']} |")
    if ref:
        w("")
        w("### Offline (deterministic, providers disabled) reference values")
        w("")
        w("| Offline metric | Offline value |")
        w("|---|---|")
        for key in ["Evidence | skill precision vs gold", "Evidence | skill recall vs gold", "Reflection | correct root-cause node rate", "Tutor | citation-existence rate", "Plan | budget utilization at 2/5/10/20 h per week"]:
            if key in ref:
                w(f"| {key.replace(' | ', ' / ')} | {ref[key]} |")
    w("")
    w("## Cases that did not pass")
    w("")
    bad = [c for c in report["cases"] if c["status"] in ("fail", "provider_error", "skipped")]
    if not bad:
        w("None.")
    else:
        w("| Area | Case | Status | Detail |")
        w("|---|---|---|---|")
        for c in bad:
            detail = c["error"] or ", ".join(c["failed_checks"]) or c["skip_reason"] or ("LLM degraded: " + ", ".join(c.get("degraded_reasons", [])) if c.get("degraded_reasons") else "")
            if c.get("first_attempt_provider_error"):
                detail += " (retried once after cooldown)"
            w(f"| {c['area']} | {c['case_id']} | {c['status']} | {detail[:180]} |")
    fb = [c for c in report["cases"] if c["status"] == "fallback"]
    if fb:
        w("")
        w("Cases completed on a deterministic fallback: " + ", ".join(f"`{c['case_id']}`" for c in fb))
    w("")
    w("## Human-readable examples")
    for area in AREA_ORDER:
        exs = [(c["case_id"], e) for c in report["cases_by_area"].get(area, []) for e in c["examples"]][:2]
        if not exs:
            continue
        w("")
        w(f"**{AREA_TITLE[area]}**")
        for cid, e in exs:
            w("")
            w(f"- `{cid}`: `{json.dumps(e, default=str)[:700]}`")
    w("")
    w("## LLM calls by schema")
    w("")
    w("| Schema | Tier | Calls | Degraded | Avg latency ms | Retried |")
    w("|---|---|---|---|---|---|")
    groups: dict[tuple, list[dict]] = {}
    for c in report["llm_calls"]:
        groups.setdefault((c["schema"], c["tier"]), []).append(c)
    for (schema, tier), cs in sorted(groups.items()):
        ok_lat = [c["latency_ms"] for c in cs if not c["degraded"]]
        w(f"| {schema} | {tier} | {len(cs)} | {sum(c['degraded'] for c in cs)} | {_fmt(_r(mean(ok_lat), 0))} | {sum(c['attempts'] > 1 for c in cs)} |")
    w("")
    return "\n".join(lines) + "\n"
