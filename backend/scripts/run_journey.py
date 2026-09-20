"""Drive the complete learner journey against a RUNNING stack and report performance.

    Resume -> Profile -> Evidence -> Skill Graph -> Gap Analysis -> Objectives -> Retrieval -> Plan ->
    Practice -> Assessment -> Struggle -> Reflection -> Re-plan -> Report -> Tutor

Uses only public HTTP endpoints (`app/demo/journey.py`), so it works against `docker compose up`, a
deployed instance, or `uvicorn` on your laptop. Each iteration is a fresh learner (own session cookie).
Per-step latency comes from the client; LLM calls / retries / planner loops / tokens / cost / retrieval
time come from the server's own persisted run records (`GET /api/runs/{run_id}`, design §31).

    # from the repo root, against the compose stack (the api container has the dependencies):
    docker compose exec api python scripts/run_journey.py --iterations 3

    # or from backend/ against any URL:
    python scripts/run_journey.py --base-url http://localhost:8000 --demo-seed --json journey.json

Exit code 0 iff every iteration completed every step (a smoke test as well as a benchmark).
`--demo-seed` needs DEMO_MODE=true on the server (POST /api/demo/seed, /api/demo/scripted-attempt).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
import uuid
from collections import defaultdict

import httpx

from app.demo.journey import JourneyDriver

# design §33.4 latency targets (seconds), keyed by journey step
TARGETS_S = {"resume_upload": 25.0, "gaps": 1.0, "plan": 15.0, "scripted_attempt": 20.0, "chat_1": 3.0, "chat_2": 3.0}


def pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[max(0, min(len(ordered) - 1, math.ceil(p / 100 * len(ordered)) - 1))]


async def run_iteration(base_url: str, demo_seed: bool, scripted: bool) -> tuple[list[dict], bool]:
    cookie = {"session": f"journey-{uuid.uuid4().hex[:12]}"}
    async with httpx.AsyncClient(base_url=base_url, cookies=cookie, timeout=120.0) as client:
        report = await JourneyDriver(client, demo_seed=demo_seed, demo_scripted_attempt=scripted).run()
        rows = []
        for step in report.steps:
            row = {"step": step.name, "status": step.status, "latency_ms": step.latency_ms, "ok": step.ok, "error": step.error, "run": None}
            if step.run_id:
                resp = await client.get(f"/api/runs/{step.run_id}")
                if resp.status_code == 200:
                    row["run"] = resp.json()
            rows.append(row)
        return rows, report.ok


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--demo-seed", action="store_true", help="seed the Asha persona via POST /api/demo/seed (needs DEMO_MODE=true)")
    parser.add_argument("--no-scripted-attempt", action="store_true", help="skip the DEMO_MODE scripted struggle step")
    parser.add_argument("--json", metavar="PATH", help="also write the raw results as JSON")
    args = parser.parse_args()

    scripted = not args.no_scripted_attempt
    all_rows: list[list[dict]] = []
    ok = True
    for i in range(args.iterations):
        rows, iteration_ok = await run_iteration(args.base_url, args.demo_seed, scripted)
        all_rows.append(rows)
        ok &= iteration_ok
        failed = [r for r in rows if not r["ok"]]
        print(f"iteration {i + 1}/{args.iterations}: {'ok' if iteration_ok else 'FAILED'}  total {sum(r['latency_ms'] for r in rows) / 1000:.2f}s", *(f"\n    x {r['step']}: {r['error']}" for r in failed))

    latency: dict[str, list[float]] = defaultdict(list)
    for rows in all_rows:
        for r in rows:
            latency[r["step"]].append(r["latency_ms"])
    print(f"\n{'step':<18}{'p50 ms':>10}{'p95 ms':>10}{'max ms':>10}{'target':>9}")
    for step, values in latency.items():
        target = TARGETS_S.get(step)
        flag = "" if target is None or max(values) / 1000 <= target else "  << over"
        print(f"{step:<18}{pct(values, 50):>10.1f}{pct(values, 95):>10.1f}{max(values):>10.1f}{(f'{target:.0f}s' if target else '-'):>9}{flag}")

    runs = [r["run"] for rows in all_rows for r in rows if r["run"]]
    totals = {
        "runs_recorded": len(runs),
        "llm_calls": sum(r["llm_calls"] for r in runs),
        "llm_retries": sum(r["llm_retries"] for r in runs),
        "llm_replays": sum(r["llm_replays"] for r in runs),
        "llm_degraded_calls": sum(r["llm_degraded"] for r in runs),
        "planner_loops": sum(r["planner_loops"] for r in runs),
        "tokens_in": sum(r["tokens_in"] for r in runs),
        "tokens_out": sum(r["tokens_out"] for r in runs),
        "cost_usd": round(sum(r["cost_usd"] for r in runs), 6),
        "retrieval_ms": round(sum(r["retrieval_ms"] for r in runs), 1),
        "degraded_runs": sum(1 for r in runs if r["degraded"]),
        "failed_runs": sum(1 for r in runs if r["status"] == "failed"),
    }
    per = {k: (round(v / args.iterations, 2) if isinstance(v, (int, float)) else v) for k, v in totals.items()}
    print(f"\nserver-side totals over {args.iterations} journeys: {json.dumps(totals)}")
    print(f"per journey: {json.dumps(per)}")
    print("design sec. 33.3 budget: ~10-20 LLM calls per demo journey" + (" (reduced-intelligence mode: every call degraded)" if totals["llm_calls"] and totals["llm_degraded_calls"] == totals["llm_calls"] else ""))

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"latency_ms": latency, "server_totals": totals, "iterations": args.iterations}, fh, indent=2, default=str)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
