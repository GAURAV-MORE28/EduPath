"""Performance (Phase 12, design §33.3-§33.4): latency, LLM calls, retries, planner loops, token usage
and retrieval speed for the complete journey -- measured from the server's own persisted run records,
not from wall-clock guesses.

These run in-process against SQLite, so absolute numbers understate a Postgres deployment's I/O; the
same measurements against the real stack come from `python scripts/run_journey.py` (see
docs/FINAL_IMPLEMENTATION_STATUS.md). The *budgets* asserted here are design §33.4's targets, which the
deterministic paths must meet with a wide margin.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db.models import AgentRun
from app.db.session import SessionLocal
from app.demo.journey import JourneyDriver
from tests.evaluation.metrics import record

pytestmark = pytest.mark.asyncio

# design §33.4 latency targets, in seconds
BUDGET_S = {"resume_upload": 25.0, "gaps": 1.0, "plan": 15.0, "scripted_attempt": 20.0, "chat_1": 3.0, "chat_2": 3.0}


async def test_journey_meets_design_latency_targets_and_reports_llm_and_planner_effort(app_client, demo_mode):
    report = await JourneyDriver(app_client, demo_seed=False).run()
    assert report.ok, [s.error for s in report.steps if not s.ok]

    over = {name: round(report.get(name).latency_ms / 1000, 2) for name, budget in BUDGET_S.items() if report.get(name).latency_ms / 1000 > budget}
    assert not over, f"over design §33.4 budget: {over}"
    slowest = max((s for s in report.steps if s.name != "preflight"), key=lambda s: s.latency_ms)
    record("Performance", "journey wall time (in-process, SQLite)", f"{report.total_ms / 1000:.2f}s", "-", f"{len(report.steps)} calls; slowest: {slowest.name} {slowest.latency_ms:.0f} ms")
    for name, budget in BUDGET_S.items():
        record("Performance", f"latency: {name}", f"{report.get(name).latency_ms:.0f} ms", f"<= {budget:.0f} s", "design §33.4")

    async with SessionLocal() as session:
        runs = (await session.execute(select(AgentRun))).scalars().all()
    journey_runs = [r for r in runs if r.run_id in set(report.run_ids)]
    llm_calls = sum(r.llm_calls for r in journey_runs)
    retries = sum(r.llm_retries for r in journey_runs)
    loops = sum(r.planner_loops for r in journey_runs)
    tokens = sum(r.tokens_in + r.tokens_out for r in journey_runs)
    retrieval_ms = sum(r.retrieval_ms for r in journey_runs)
    plan_run = next(r for r in journey_runs if r.route == "/api/learners/me/plans" and r.method == "POST")

    record("Performance", "LLM calls per journey", llm_calls, "design budget ~10-20", "LLM_PROVIDER=none: each call degrades at once to its deterministic path")
    record("Performance", "LLM degraded calls", sum(r.llm_degraded for r in journey_runs), "report")
    record("Performance", "agent retries per journey", retries, "<= 2 per agent call (bounded)")
    record("Performance", "planner loops (plan run)", plan_run.planner_loops, "<= 3 (1 draft + 2 retries)")
    record("Performance", "tokens per journey", tokens, "report", "0 without a provider; real usage is recorded per LLM call")
    record("Performance", "retrieval time per journey", f"{retrieval_ms:.0f} ms", "report", "sum over every Resource Retriever call")
    assert 1 <= plan_run.planner_loops <= 3, "planner loops are bounded (design §9.4: retry <= 2)"
    assert retries <= 2 * max(llm_calls, 1)
    assert all(r.llm_degraded <= r.llm_calls for r in journey_runs)
    assert retrieval_ms > 0 and plan_run.retrieval_ms > 0


async def test_retrieval_is_fast_per_skill(catalog_session):
    import time

    from app.gateway.embedding_gateway import DegradedEmbeddingGateway
    from app.graph.loader import GraphLoader
    from app.graph.queries import SkillGraphService
    from app.repositories.catalog_repository import CatalogRepository
    from app.retrieval.service import ResourceRetrievalService

    catalog = CatalogRepository(catalog_session)
    graph = SkillGraphService(await GraphLoader(catalog).load())
    service = ResourceRetrievalService(catalog, graph, DegradedEmbeddingGateway())
    skills = sorted(graph.role_subgraph("role.ml_engineer").skill_ids)[:40]
    everything = {s.skill_id for s in await catalog.get_all_skills()}
    timings = []
    for sid in skills:
        started = time.perf_counter()
        await service.recommend_for_skill(skill_id=sid, current_level=0, met_skill_ids=everything, session_cap_minutes=10_000)
        timings.append((time.perf_counter() - started) * 1000)
    timings.sort()
    p50, p95 = timings[len(timings) // 2], timings[int(len(timings) * 0.95) - 1]
    record("Performance", "retrieval latency per skill (p50 / p95)", f"{p50:.1f} / {p95:.1f} ms", "< 500 ms", f"{len(skills)} skills, full hybrid retrieval + ranking + MMR")
    assert p95 < 500


async def test_gap_analysis_is_under_one_second_for_the_largest_role(catalog_session):
    import time

    from app.gap.engine import analyze_gaps
    from app.graph.loader import GraphLoader
    from app.graph.queries import SkillGraphService
    from app.repositories.catalog_repository import CatalogRepository

    graph = SkillGraphService(await GraphLoader(CatalogRepository(catalog_session)).load())
    started = time.perf_counter()
    for _ in range(20):
        analyze_gaps("role.backend_developer", [], [], graph)
    per_call_ms = (time.perf_counter() - started) * 1000 / 20
    record("Performance", "gap analysis, empty learner, largest role", f"{per_call_ms:.1f} ms", "< 1 s (design §33.4)")
    assert per_call_ms < 1000
