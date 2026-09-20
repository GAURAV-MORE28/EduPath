"""Live LLM evaluation & quality baseline (docs/LLM_EVALUATION.md).

    cd backend
    python scripts/evaluate_llm.py --mode live --suite smoke     # compact, ~40 LLM calls
    python scripts/evaluate_llm.py --mode live --suite full      # every gold case
    python scripts/evaluate_llm.py --mode live --suite smoke --areas profiling,tutor
    python scripts/evaluate_llm.py --mode offline                # the existing deterministic evaluation (providers off)

LIVE mode uses the providers configured in backend/.env (LLM / embeddings / vision / web search) through the project's
own gateways -- nothing is mocked and a disabled provider is a hard error, not a silent offline run. The app runs
in-process on an in-memory SQLite database, so no real database or learner is touched. Every LLM call is measured
(latency, retries, error category, fallback); no secret is ever printed or written.

Reports: reports/llm_eval/<UTC timestamp>_<suite>.{json,md}  (+ reports/llm_eval/latest_<suite>.{json,md}).
Exit code 0 unless the run could not be executed or a HARD invariant failed (`--strict` also fails on provider errors).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_ROOT)  # pydantic reads .env relative to the cwd
sys.path.insert(0, str(BACKEND_ROOT))

from tests.evaluation.live import runner  # noqa: E402  (must precede any `app` import)


def log(message: str) -> None:
    print(message, flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", choices=["live", "offline"])
    parser.add_argument("--merge", nargs="+", metavar="REPORT.json", help="combine previous live reports (best-measured result per case, provenance kept) and re-render; makes no provider calls")
    parser.add_argument("--out-name", default="baseline_live", help="file stem for --merge output")
    parser.add_argument("--suite", choices=["smoke", "full"], default="smoke")
    parser.add_argument("--areas", help="comma-separated subset: profiling,gap,planner,assessor,reflection,tutor,web,vision,known_issues")
    parser.add_argument("--min-interval", type=float, default=2.0, help="seconds to wait after an LLM-bearing case (default 2.0)")
    parser.add_argument("--tpm", type=float, default=6000.0, help="token-per-minute pacing budget for LLM-bearing cases (0 = no token pacing; default 6000, "
                        "conservative for a free-tier provider)")
    parser.add_argument("--out-dir", default=str(runner.REPORT_DIR))
    parser.add_argument("--strict", action="store_true", help="exit non-zero on provider-error cases too")
    args = parser.parse_args()

    if args.merge:
        from tests.evaluation.live.report import render_markdown

        merged = runner.merge_reports([json.loads(Path(p).read_text(encoding="utf-8")) for p in args.merge])
        out = Path(args.out_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{args.out_name}.json").write_text(json.dumps(merged, indent=2, default=runner._json_default), encoding="utf-8")
        (out / f"{args.out_name}.md").write_text(render_markdown(merged), encoding="utf-8")
        t = merged["technical"]
        log(f"merged {len(args.merge)} report(s): cases {t['total_cases']} | pass {t['successful_cases']} | fallback {t['fallback_cases']} | fail {t['failed_cases']} | "
            f"provider-error {t['provider_error_cases']} | skipped {t['skipped_cases']} -> {out / (args.out_name + '.md')}")
        return 0
    if args.mode is None:
        parser.error("--mode is required (or use --merge)")
    if args.mode == "offline":
        return runner.run_offline(log)

    runner.prepare_environment()
    areas = {a.strip() for a in args.areas.split(",")} if args.areas else None
    try:
        report = asyncio.run(runner.run_evaluation(args.suite, areas, args.min_interval, log, args.tpm))
    except runner.LiveConfigError as exc:
        log(f"CONFIG ERROR: {exc}")
        return 2

    from tests.evaluation.live.report import render_markdown

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stamp = report["meta"]["timestamp_utc"].replace(":", "").replace("-", "")
    md = render_markdown(report)
    payload = json.dumps(report, indent=2, default=runner._json_default)
    for name in (f"{stamp}_{args.suite}", f"latest_{args.suite}"):
        (out / f"{name}.json").write_text(payload, encoding="utf-8")
        (out / f"{name}.md").write_text(md, encoding="utf-8")

    t = report["technical"]
    log("")
    log(f"cases {t['total_cases']}: pass {t['successful_cases']} | fallback {t['fallback_cases']} | fail {t['failed_cases']} | "
        f"provider-error {t['provider_error_cases']} | skipped {t['skipped_cases']}")
    log(f"LLM calls {t['llm_calls']} (degraded {t['llm_calls_degraded']}), retries {t['gateway_retries']}+{t['agent_schema_retries']}, "
        f"p50/p95 {t['llm_call_latency_ms']['p50']}/{t['llm_call_latency_ms']['p95']} ms")
    log(f"report: {out / ('latest_' + args.suite + '.md')}")
    if t["failed_cases"]:
        return 1
    return 1 if args.strict and t["provider_error_cases"] else 0


if __name__ == "__main__":
    sys.exit(main())
