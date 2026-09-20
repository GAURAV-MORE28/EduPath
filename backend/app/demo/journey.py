"""The complete learner journey, driven over HTTP.

    Resume -> Profile -> Evidence -> Skill Graph -> Gap Analysis -> Objectives ->
    Retrieval -> Plan -> Practice -> Assessment -> Struggle -> Reflection ->
    Re-plan -> Report -> Tutor

One driver, three users: the end-to-end integration test (in-process ASGI),
`scripts/run_journey.py` (a running stack, e.g. after `docker compose up`, for
smoke checks / benchmarking / recording LLM responses) and the demo rehearsal.
It only calls public endpoints; the client owns the session cookie, so a
fresh `httpx.AsyncClient` is a fresh learner. It never reads answer keys --
the struggle step uses `POST /api/demo/scripted-attempt` (DEMO_MODE), which
resolves the scripted answers server-side.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.demo.service import load_demo_learner, load_demo_resume, load_scenario

TUTOR_QUESTIONS_FALLBACK = ["Why did my plan change?", "Why do I need the chain rule for PyTorch training?"]


@dataclass
class StepResult:
    name: str
    status: int
    latency_ms: float
    run_id: str | None
    payload: Any = None
    ok: bool = True
    error: str | None = None


@dataclass
class JourneyReport:
    steps: list[StepResult] = field(default_factory=list)

    def get(self, name: str) -> StepResult:
        return next(s for s in self.steps if s.name == name)

    def payload(self, name: str) -> Any:
        return self.get(name).payload

    @property
    def ok(self) -> bool:
        return all(s.ok for s in self.steps)

    @property
    def total_ms(self) -> float:
        return sum(s.latency_ms for s in self.steps)

    @property
    def run_ids(self) -> list[str]:
        return [s.run_id for s in self.steps if s.run_id]


class JourneyDriver:
    def __init__(self, client: httpx.AsyncClient, *, demo_scripted_attempt: bool = True, demo_seed: bool = False) -> None:
        self.client = client
        self.demo_scripted_attempt = demo_scripted_attempt
        self.demo_seed = demo_seed  # True: seed Asha via POST /api/demo/seed instead of the manual intake -> upload -> confirm steps
        self.report = JourneyReport()

    async def _call(self, name: str, method: str, path: str, *, expect: tuple[int, ...] = (200, 201), **kwargs: Any) -> StepResult:
        started = time.perf_counter()
        error: str | None = None
        try:
            response = await self.client.request(method, path, **kwargs)
            status, run_id = response.status_code, response.headers.get("x-run-id")
            try:
                payload = response.json()
            except ValueError:
                payload = response.text
            if status not in expect:
                error = f"{method} {path} -> {status}: {str(payload)[:300]}"
        except httpx.HTTPError as exc:
            status, run_id, payload, error = 0, None, None, f"{method} {path} failed: {type(exc).__name__}"
        step = StepResult(name, status, (time.perf_counter() - started) * 1000.0, run_id, payload, error is None, error)
        self.report.steps.append(step)
        return step

    async def run(self) -> JourneyReport:
        learner = load_demo_learner()
        scenario = load_scenario()

        await self._call("health", "GET", "/api/health")
        await self._call("preflight", "GET", "/api/demo/preflight")

        # Resume -> Profile -> Evidence
        if self.demo_seed:
            if not (await self._call("demo_seed", "POST", "/api/demo/seed")).ok:
                return self.report
        else:
            intake = await self._call(
                "intake", "POST", "/api/learners",
                json={
                    "current_skills": ["Python", "PyTorch", "OpenCV"],
                    "experience_summary": learner["experience_summary"],
                    "target_role_id": learner["target_role_id"],
                    "career_goal": learner["career_goal"],
                    "weekly_hours": learner["weekly_hours"],
                    "preferences": {"modality_order": learner["preferences"]["modality_order"], "language": "en", "session_length_min": 60},
                },
            )
            if not intake.ok:
                return self.report
            await self._call("resume_upload", "POST", "/api/learners/me/documents", files={"file": ("demo_resume.md", load_demo_resume(), "text/markdown")})
            pending = await self._call("claims_pending", "GET", "/api/learners/me/claims/pending")
            claims = pending.payload if isinstance(pending.payload, list) else []
            decisions = [{"claim_id": c["claim_id"], "action": "confirm" if c.get("normalized_skill_id") else "remove"} for c in claims]
            await self._call("claims_confirm", "POST", "/api/learners/me/claims/confirm", json={"decisions": decisions})
        await self._call("evidence", "GET", "/api/learners/me/evidence")

        # Skill Graph -> Gap Analysis -> Objectives
        target_skill = scenario["seeded_misconception"]["affected_skill"]
        await self._call("skill_graph", "GET", f"/api/learners/me/skills/{target_skill}")
        await self._call("gaps", "GET", "/api/learners/me/gaps")

        # Retrieval -> Plan
        await self._call("plan", "POST", "/api/learners/me/plans", json={})
        await self._call("plan_current", "GET", "/api/learners/me/plans/current")

        # Practice -> Assessment -> Struggle -> Reflection -> Re-plan
        await self._call("practice", "POST", "/api/learners/me/practice", json={"skill_id": target_skill, "purpose": "practice"})
        if self.demo_scripted_attempt:
            await self._call("scripted_attempt", "POST", "/api/demo/scripted-attempt")
        await self._call("plan_after", "GET", "/api/learners/me/plans/current")
        await self._call("revisions", "GET", "/api/learners/me/plans/current/revisions")

        # Report -> Tutor
        await self._call("progress", "GET", "/api/learners/me/progress")
        revised = self.report.get("scripted_attempt").payload if self.demo_scripted_attempt else None
        decision_id = ((revised or {}).get("reflection") or {}).get("decision_id") if isinstance(revised, dict) else None
        for i, question in enumerate(scenario.get("tutor_demo_questions") or TUTOR_QUESTIONS_FALLBACK):
            body: dict[str, Any] = {"message": question}
            if i == 0 and decision_id:
                body["decision_id_hint"] = decision_id
            await self._call(f"chat_{i + 1}", "POST", "/api/learners/me/chat", json=body)
        if decision_id:
            await self._call("decision", "GET", f"/api/decisions/{decision_id}")
        await self._call("my_runs", "GET", "/api/learners/me/runs")
        return self.report
