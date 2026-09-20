"""Evaluation: plan quality over diverse learner personas (design §32.2 "Plan quality", §17.3).

Ten personas (three roles, 2-20 h/week, empty / claimed / documented evidence, different modality
preferences and session caps) each get a plan through the real API. Checked independently of the
Planner's own validator: budget, referential integrity (real, healthy, catalogued resources),
prerequisite order against the Gap Engine's own statuses, and personalization across personas.
"""
from __future__ import annotations

import itertools

import pytest
from sqlalchemy import select

from app.db import models as m
from app.db.session import SessionLocal
from tests.evaluation.metrics import record

pytestmark = pytest.mark.asyncio

PERSONAS = [
    {"id": "ml-novice-5h", "role": "role.ml_engineer", "hours": 5, "skills": []},
    {"id": "ml-claims-8h", "role": "role.ml_engineer", "hours": 8, "skills": ["Python", "PyTorch", "OpenCV"]},
    {"id": "ml-heavy-20h", "role": "role.ml_engineer", "hours": 20, "skills": ["Python", "NumPy", "pandas", "scikit-learn"]},
    {"id": "ml-tiny-2h", "role": "role.ml_engineer", "hours": 2, "skills": ["Python"]},
    {"id": "da-10h", "role": "role.data_analyst", "hours": 10, "skills": ["SQL", "Excel"]},
    {"id": "da-novice-4h", "role": "role.data_analyst", "hours": 4, "skills": []},
    {"id": "be-12h", "role": "role.backend_developer", "hours": 12, "skills": ["Python", "Git", "Docker"]},
    {"id": "be-watch-6h", "role": "role.backend_developer", "hours": 6, "skills": ["JavaScript"], "modality": ["watch", "read", "do"]},
    {"id": "be-short-sessions", "role": "role.backend_developer", "hours": 9, "skills": ["Python"], "session": 30},
    {"id": "da-read-7h", "role": "role.data_analyst", "hours": 7, "skills": ["Python", "Tableau"], "modality": ["read", "do", "watch"]},
]


async def _plan_for(client, persona: dict):
    client.cookies.set("session", f"plan-eval-{persona['id']}")
    prefs = {"modality_order": persona.get("modality", ["do", "watch", "read"]), "language": "en", "session_length_min": persona.get("session", 45)}
    body = {"current_skills": persona["skills"], "experience_summary": "", "target_role_id": persona["role"], "career_goal": "", "weekly_hours": persona["hours"], "preferences": prefs}
    assert (await client.post("/api/learners", json=body)).status_code == 201
    plan = await client.post("/api/learners/me/plans", json={})
    assert plan.status_code == 200, persona["id"]
    gaps = (await client.get("/api/learners/me/gaps")).json()
    return plan.json(), gaps


async def test_plans_are_valid_feasible_and_prerequisite_ordered_across_personas(app_client):
    async with SessionLocal() as session:
        resources = {r.resource_id: r for r in (await session.execute(select(m.Resource))).scalars().all()}
    plans: dict[str, dict] = {}
    invalid: list[str] = []
    over_budget = blocked_scheduled = order_violations = unknown = broken = items_total = 0
    empty = 0

    for persona in PERSONAS:
        plan, gaps = await _plan_for(app_client, persona)
        plans[persona["id"]] = plan
        items = plan["items"]
        items_total += len(items)
        empty += not items
        budget_min = persona["hours"] * 60
        if sum(i["est_minutes"] for i in items) > budget_min:
            over_budget += 1
            invalid.append(f"{persona['id']}: over budget")
        status = {g["skill_id"]: g["status"] for g in gaps["gaps"]}
        day = {}
        for item in items:
            day.setdefault(item["skill_id"], item["day_slot"])
            day[item["skill_id"]] = min(day[item["skill_id"]], item["day_slot"])
            if item["resource_id"]:
                r = resources.get(item["resource_id"])
                unknown += r is None
                broken += r is not None and r.link_status != "ok"
            blocked_scheduled += status.get(item["skill_id"]) == "BLOCKED"  # V3: a BLOCKED skill's root comes first, not the skill
        # prerequisite order against the engine's own edges: a scheduled skill never precedes a scheduled hard prerequisite
        for edge in gaps["prerequisite_edges"]:
            prereq, skill = edge["from_skill_id"], edge["to_skill_id"]
            if prereq in day and skill in day:
                order_violations += day[prereq] > day[skill]

    n = len(PERSONAS)
    record("Plan", "final validity (budget / referential integrity / prerequisite order)", 1 - len(invalid) / n, "1.00", f"{n} personas, {items_total} items; first-attempt LLM validity n/a (LLM_PROVIDER=none -> deterministic fallback planner)")
    record("Plan", "personas producing an empty week", empty, "0")
    assert not invalid, invalid
    assert unknown == 0 and broken == 0, "every scheduled resource is a real, healthy catalog resource"
    assert blocked_scheduled == 0 and order_violations == 0
    assert empty == 0

    # personalization: different learners get different weeks (Jaccard distance over scheduled (skill, resource) pairs)
    sets = {pid: {(i["skill_id"], i["resource_id"]) for i in plan["items"]} for pid, plan in plans.items()}
    distances = [1 - len(sets[a] & sets[b]) / len(sets[a] | sets[b]) for a, b in itertools.combinations(sets, 2) if sets[a] | sets[b]]
    mean_distance = sum(distances) / len(distances)
    role_of = {p["id"]: p["role"] for p in PERSONAS}
    cross_role = [1 - len(sets[a] & sets[b]) / len(sets[a] | sets[b]) for a, b in itertools.combinations(sets, 2) if role_of[a] != role_of[b]]
    record("Plan", "personalization (mean pairwise Jaccard distance)", mean_distance, "> 0.3", f"across {len(distances)} persona pairs")
    assert mean_distance > 0.3 and min(cross_role) > 0.0


async def test_more_hours_never_produces_a_smaller_week(app_client):
    """Feasibility monotonicity: the same learner with more weekly hours is never scheduled *less* learning time."""
    minutes = {}
    for hours in (2, 5, 10, 20):
        plan, _ = await _plan_for(app_client, {"id": f"mono-{hours}", "role": "role.ml_engineer", "hours": hours, "skills": ["Python"]})
        minutes[hours] = sum(i["est_minutes"] for i in plan["items"])
        assert minutes[hours] <= hours * 60
    assert minutes[2] <= minutes[5] <= minutes[10] <= minutes[20], minutes
    record("Plan", "scheduled minutes at 2/5/10/20 h per week", "/".join(str(minutes[h]) for h in (2, 5, 10, 20)), "non-decreasing")
    record(
        "Plan", "budget utilization at 2/5/10/20 h per week", " / ".join(f"{minutes[h] / (h * 60):.0%}" for h in (2, 5, 10, 20)), "report",
        "KNOWN LIMITATION: the plan is feasible (never over budget) but under-fills large budgets -- the 45-min session cap "
        "removes course-length resources (see the 'coverage at the default 45-min session cap' row) and there is no segment splitting",
    )


async def test_a_dry_run_plan_persists_nothing(app_client):
    persona = {"id": "dry-run", "role": "role.ml_engineer", "hours": 6, "skills": ["Python"]}
    await _plan_for(app_client, persona)
    async with SessionLocal() as session:
        before = len((await session.execute(select(m.PlanRevision))).scalars().all())
    resp = await app_client.post("/api/learners/me/plans", json={"dry_run": True, "hours": 3})
    assert resp.status_code == 200 and resp.json()["items"] is not None
    async with SessionLocal() as session:
        assert len((await session.execute(select(m.PlanRevision))).scalars().all()) == before
