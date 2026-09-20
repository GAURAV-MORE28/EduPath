"""Observability (Phase 12): every important action has a run id, step ids, learner id,
actor, references, decision link, duration, token/cost and status -- persisted
(`agent_runs` / `agent_steps`), readable by its owner only, aggregated at `/api/metrics`
(design §28, §31)."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db.models import AgentRun, AgentStep
from app.db.session import SessionLocal
from app.observability.context import RunContext
from app.observability.store import persist_run
from app.sse.trace import emit, span, trace_bus

pytestmark = pytest.mark.asyncio

INTAKE = {"current_skills": ["Python"], "experience_summary": "", "target_role_id": "role.ml_engineer", "career_goal": "ML", "weekly_hours": 6}


async def _run(run_id: str):
    async with SessionLocal() as session:
        run = await session.get(AgentRun, run_id)
        steps = (await session.execute(select(AgentStep).where(AgentStep.run_id == run_id).order_by(AgentStep.seq))).scalars().all()
    return run, steps


async def test_every_api_response_carries_a_run_id_header(app_client):
    resp = await app_client.post("/api/learners", json=INTAKE)
    assert resp.status_code == 201
    generated = resp.headers["x-run-id"]
    assert len(generated) >= 8

    resp = await app_client.post("/api/learners/me/plans", json={}, headers={"X-Run-Id": "client-chosen-run-01"})
    assert resp.headers["x-run-id"] == "client-chosen-run-01"

    # a malformed client id is ignored (never trusted into a primary key / SSE channel)
    resp = await app_client.post("/api/learners/me/plans", json={"dry_run": True}, headers={"X-Run-Id": "bad id; drop table"})
    assert resp.headers["x-run-id"] != "bad id; drop table"


async def test_plan_run_records_identity_counters_steps_and_durations(app_client):
    await app_client.post("/api/learners", json=INTAKE)
    resp = await app_client.post("/api/learners/me/plans", json={}, headers={"X-Run-Id": "obs-plan-run-0001"})
    assert resp.status_code == 200

    run, steps = await _run("obs-plan-run-0001")
    assert run is not None
    assert run.learner_id and run.user_id == "dev-user"
    assert (run.method, run.route, run.graph, run.http_status) == ("POST", "/api/learners/me/plans", "planning", 200)
    assert run.status in {"completed", "degraded"} and run.duration_ms > 0 and run.ended_at is not None
    assert run.llm_calls >= 1 and run.planner_loops >= 1 and run.retrieval_ms > 0
    assert run.llm_degraded == run.llm_calls  # LLM_PROVIDER=none: every call degraded, and counted as such

    assert steps, "the plan run recorded trace steps"
    assert [s.seq for s in steps] == list(range(1, len(steps) + 1))
    assert len({s.step_id for s in steps}) == len(steps)
    assert all(s.learner_id == run.learner_id and s.actor and s.kind and s.duration_ms >= 0 and s.status in {"ok", "degraded", "error"} for s in steps)
    actors = {s.actor for s in steps}
    assert {"Gap Engine", "Planner", "LLM Gateway", "Resource Retriever"} <= actors
    gateway_steps = [s for s in steps if s.actor == "LLM Gateway"]
    assert gateway_steps and all(s.status == "degraded" and s.output_ref for s in gateway_steps)


async def test_audit_only_steps_are_not_pushed_to_the_learner_facing_trace_stream(app_client):
    await app_client.post("/api/learners", json=INTAKE)
    await app_client.post("/api/learners/me/plans", json={}, headers={"X-Run-Id": "obs-stream-run-01"})
    queue = trace_bus.subscribe("obs-stream-run-01")
    streamed = []
    while not queue.empty():
        streamed.append(queue.get_nowait().agent_or_service)
    trace_bus.unsubscribe("obs-stream-run-01", queue)
    assert streamed and "LLM Gateway" not in streamed and "Resource Retriever" not in streamed

    _, steps = await _run("obs-stream-run-01")
    assert {"LLM Gateway", "Resource Retriever"} <= {s.actor for s in steps}  # ...but they are in the audit trail


async def test_reflection_decision_is_linked_from_its_trace_step(app_client, demo_mode):
    await app_client.post("/api/demo/seed")
    resp = await app_client.post("/api/demo/scripted-attempt")
    reflection = resp.json()["reflection"]
    run, steps = await _run(resp.headers["x-run-id"])
    linked = [s for s in steps if s.decision_id]
    assert len(linked) == 1 and linked[0].decision_id == reflection["decision_id"]
    assert linked[0].output_ref == reflection["plan_revision_id"] and linked[0].input_ref
    assert run.graph == "demo"


async def test_run_detail_is_visible_to_its_owner_only(app_client, other_client):
    await app_client.post("/api/learners", json=INTAKE)
    resp = await app_client.post("/api/learners/me/plans", json={}, headers={"X-Run-Id": "obs-owner-run-001"})
    assert resp.status_code == 200

    mine = await app_client.get("/api/runs/obs-owner-run-001")
    assert mine.status_code == 200
    body = mine.json()
    assert body["run_id"] == "obs-owner-run-001" and body["steps"] and body["steps"][0]["run_id"] == "obs-owner-run-001"

    assert (await other_client.get("/api/runs/obs-owner-run-001")).status_code == 404  # a foreign run looks like an unknown one
    assert (await app_client.get("/api/runs/does-not-exist-000")).status_code == 404
    assert (await other_client.get("/api/learners/me/runs")).json() == []
    assert [r["run_id"] for r in (await app_client.get("/api/learners/me/runs")).json()][:1] == ["obs-owner-run-001"]


async def test_metrics_endpoint_aggregates_without_learner_identifiers(app_client):
    await app_client.post("/api/learners", json=INTAKE)
    await app_client.post("/api/learners/me/plans", json={})
    resp = await app_client.get("/api/metrics")
    assert resp.status_code == 200
    metrics = resp.json()
    assert metrics["window_runs"] >= 2
    planning = metrics["by_graph"]["planning"]
    assert planning["runs"] == 1 and planning["planner_loops"] >= 1 and planning["llm_calls"] >= 1
    assert planning["latency_ms"]["p50"] > 0 and planning["latency_ms"]["p95"] >= planning["latency_ms"]["p50"]
    assert set(planning) >= {"llm_retries", "llm_replays", "tokens_in", "tokens_out", "cost_usd", "retrieval_ms_total", "degraded_run_rate", "failed_run_rate"}
    assert "learner" not in resp.text.lower()


async def test_a_failed_run_is_recorded_as_failed_with_its_error(app_client):
    ctx = RunContext(run_id="obs-failed-run-001", client_supplied=False, method="POST", route="/api/learners/me/plans", user_id="u1")
    ctx.add_step("Planner", "error", "boom", status="error")
    await persist_run(ctx, http_status=500, error="RuntimeError: boom")
    run, steps = await _run("obs-failed-run-001")
    assert run.status == "failed" and run.http_status == 500 and run.error == "RuntimeError: boom"
    assert steps[0].status == "error"


async def test_a_reused_run_id_keeps_both_audit_records(app_client):
    for _ in range(2):
        await app_client.post("/api/learners", json=INTAKE, headers={"X-Run-Id": "obs-reused-run-001"})
    async with SessionLocal() as session:
        ids = [r.run_id for r in (await session.execute(select(AgentRun))).scalars().all() if r.run_id.startswith("obs-reused-run-001")]
    assert len(ids) == 2


async def test_a_broken_audit_write_never_fails_the_request(app_client, monkeypatch):
    import app.observability.store as store

    class Boom:
        def __init__(self, *a, **k):
            raise RuntimeError("audit store down")

    monkeypatch.setattr(store, "AgentRun", Boom)
    resp = await app_client.post("/api/learners", json=INTAKE)
    assert resp.status_code == 201


async def test_span_records_real_duration_and_marks_failures():
    ctx = RunContext(run_id="obs-span-run-0001", client_supplied=False)
    from app.observability.context import current_run

    token = current_run.set(ctx)
    try:
        async with span("Resource Retriever", "retrieval", "ranked 3", refs=["skill.a"]) as s:
            s.output_ref = "res.x"
        with pytest.raises(ValueError):
            async with span("Planner", "output", "drafting"):
                raise ValueError("bad")
        await emit("Gap Engine", "decision", "done", decision_id="d1", input_ref="i", output_ref="o")
    finally:
        current_run.reset(token)
    ok, failed, plain = ctx.steps
    assert ok.output_ref == "res.x" and ok.status == "ok" and ok.duration_ms >= 0
    assert failed.kind == "error" and failed.status == "error" and "ValueError" in failed.summary
    assert plain.decision_id == "d1" and (plain.input_ref, plain.output_ref) == ("i", "o")


async def test_unhandled_errors_carry_cors_headers_for_the_frontend_origin(app_client):
    """Phase 11 known issue: Starlette answers a 500 outside CORSMiddleware, so the browser
    reported a real 500 as an opaque network error."""
    import httpx

    from app.config import get_settings
    from app.main import app

    async def explode():
        raise RuntimeError("kaboom")

    app.add_api_route("/api/_test_explode", explode, methods=["GET"])
    try:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            origin = get_settings().frontend_origin
            resp = await client.get("/api/_test_explode", headers={"Origin": origin})
            assert resp.status_code == 500 and resp.json()["error"]["code"] == "internal_error"
            assert resp.headers["access-control-allow-origin"] == origin
            other = await client.get("/api/_test_explode", headers={"Origin": "https://evil.example"})
            assert "access-control-allow-origin" not in other.headers
    finally:
        app.router.routes[:] = [r for r in app.router.routes if getattr(r, "path", "") != "/api/_test_explode"]
