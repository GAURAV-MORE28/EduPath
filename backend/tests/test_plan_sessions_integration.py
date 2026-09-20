"""Stage 2 end to end on the real curated catalog (`catalog_session` / `app_client` fixtures): candidate sessionization from
real `Resource` rows, the G2 Planning graph on both paths (deterministic fallback after a provider failure; a scripted "LLM"
draft that selects real sessions), multi-week continuation through the API, and persistence of session provenance.

Test-matrix rows covered here: D (several weeks), F/G (large & small budgets on real data), H (planner LLM failure -> fallback),
I (invalid session candidate from a model), J (no duplicate sessions), L (existing behaviour on the real pipeline), and the
provenance / no-hallucinated-structure guarantees. Row M (live planner output) is the live evaluation, not a deterministic test.
"""
from __future__ import annotations

import json

import pytest
from sqlalchemy import select, update

from app.agents.planner import PlannerAgent
from app.db import models as m
from app.db.session import SessionLocal
from app.gap.engine import analyze_gaps
from app.gateway.embedding_gateway import DegradedEmbeddingGateway
from app.gateway.llm_gateway import LLMGateway, LLMResponse
from app.graph.loader import GraphLoader
from app.graph.queries import SkillGraphService
from app.orchestration.graphs import build_planning_graph
from app.orchestration.state import RunState
from app.planning.candidates import build_candidate_sets
from app.planning.sessions import SessionizationPolicy, segment_durations
from app.planning.validator import effective_budget_minutes, validate_plan
from app.repositories.catalog_repository import CatalogRepository
from app.retrieval.service import ResourceRetrievalService
from tests.evaluation.test_eval_plan_validity import PERSONAS, _plan_for

ROLE = "role.ml_engineer"


@pytest.fixture
async def graph_service(catalog_session) -> SkillGraphService:
    return SkillGraphService(await GraphLoader(CatalogRepository(catalog_session)).load())


class ScriptedLLM(LLMGateway):
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls = 0

    async def complete(self, request):  # noqa: D102
        self.calls += 1
        return LLMResponse(raw_text=self._responses.pop(0) if self._responses else "not json", degraded=False)


async def _run_graph(catalog_session, graph_service, agent: PlannerAgent, *, hours: float, session_cap: int = 45, consumed=None):
    catalog = CatalogRepository(catalog_session)
    retrieval = ResourceRetrievalService(catalog, graph_service, DegradedEmbeddingGateway())
    graph = build_planning_graph(graph_service=graph_service, planner_agent=agent, catalog=catalog, retrieval_service=retrieval)
    state: RunState = {
        "run_id": "run-sessions", "learner_id": "learner-sessions", "graph": "G2_planning", "status": "running", "counters": {},
        "data": {
            "role_id": ROLE, "skill_records": [], "evidence_records": [], "hours_budget_minutes": effective_budget_minutes(hours),
            "session_cap_minutes": session_cap, "consumed_session_ids": consumed,
        },
    }
    return (await graph.ainvoke(state))["data"]


def _validate(d, items, graph_service):
    gaps_by_skill = {g.skill_id: g for g in d["gap_result"].gaps}
    return validate_plan(
        items, candidate_sets=d["candidate_sets"], gaps_by_skill=gaps_by_skill,
        hard_prereqs_by_skill={s: graph_service.direct_prerequisites(s, include_soft=False) for s in gaps_by_skill},
        hours_budget_minutes=d["hours_budget_minutes"], enforce_sessions=True,
    )


async def _assert_sessions_are_real(catalog_session, items, *, cap: int = 45):
    """Independent of the planner's own code path: recompute every session from the raw catalog row."""
    rows = {r.resource_id: r for r in await CatalogRepository(catalog_session).get_all_resources()}
    consumed: dict[str, int] = {}
    seen: set[str] = set()
    for i in items:
        if i.resource_id is None:
            assert i.session is None
            continue
        row = rows[i.resource_id]  # the resource exists in the catalog
        assert row.link_status == "ok"
        assert i.session is not None, "every resource item carries session provenance"
        s = i.session
        parts = segment_durations(row.duration_min, SessionizationPolicy.for_learner(cap))
        assert s.resource_id == row.resource_id and s.session_id == f"{row.resource_id}#{s.index}"
        assert s.count == len(parts) and 1 <= s.index <= s.count and s.resource_duration_min == row.duration_min
        assert i.est_minutes == parts[s.index - 1] <= cap
        assert s.label == (row.title if s.count == 1 else f"{row.title} — Study Segment {s.index} of {s.count}")
        assert s.session_id not in seen, "no duplicate session"
        seen.add(s.session_id)
        consumed[row.resource_id] = consumed.get(row.resource_id, 0) + i.est_minutes
    for rid, minutes in consumed.items():
        assert minutes <= rows[rid].duration_min, f"{rid}: sessions total more than the resource's duration"


# -- candidates from real catalog rows -----------------------------------------------------------------------------------


async def test_long_catalog_resources_are_offered_as_real_sessions_instead_of_being_dropped(catalog_session, graph_service):
    catalog = CatalogRepository(catalog_session)
    retrieval = ResourceRetrievalService(catalog, graph_service, DegradedEmbeddingGateway())
    gap = analyze_gaps(ROLE, [], [], graph_service)
    sets = await build_candidate_sets(gap_result=gap, retrieval_service=retrieval, catalog=catalog, session_cap_minutes=45)
    rows = {r.resource_id: r for r in await catalog.get_all_resources()}

    resources = [r for cs in sets.values() for r in cs.resources]
    assert any(r.duration_min > 45 and len(r.sessions) > 1 for r in resources), "course-length resources are now candidates"
    for r in resources:
        row = rows[r.resource_id]
        assert [s.session_id for s in r.sessions] == [f"{row.resource_id}#{n}" for n in range(1, len(r.sessions) + 1)]
        assert sum(s.est_minutes for s in r.sessions) == row.duration_min
        assert all(s.est_minutes <= 45 and s.resource_id == row.resource_id and s.url == row.url and s.title == row.title for s in r.sessions)

    # the objectives that had no candidate at the cap (the thin-plan cause) now have one
    with_cap_only = 0
    for cs in sets.values():
        if cs.objective_type != "lesson":
            continue
        recs = await retrieval.recommend_for_skill(skill_id=cs.skill_id, current_level=cs.current_level, session_cap_minutes=45, sessionizable=False)
        with_cap_only += bool(recs)
    with_sessions = sum(1 for cs in sets.values() if cs.objective_type == "lesson" and cs.resources)
    assert with_sessions > with_cap_only


async def test_consumed_sessions_are_removed_and_numbering_stays_stable(catalog_session, graph_service):
    catalog = CatalogRepository(catalog_session)
    retrieval = ResourceRetrievalService(catalog, graph_service, DegradedEmbeddingGateway())
    gap = analyze_gaps(ROLE, [], [], graph_service)
    base = await build_candidate_sets(gap_result=gap, retrieval_service=retrieval, catalog=catalog)
    res = next(r for cs in base.values() for r in cs.resources if len(r.sessions) >= 4)
    done = {s.session_id for s in res.sessions[:2]}

    after = await build_candidate_sets(gap_result=gap, retrieval_service=retrieval, catalog=catalog, consumed_session_ids=done)
    again = next(r for cs in after.values() for r in cs.resources if r.resource_id == res.resource_id)
    assert [s.index for s in again.sessions] == list(range(3, len(res.sessions) + 1))
    assert {s.count for s in again.sessions} == {len(res.sessions)}

    everything = {s.session_id for s in res.sessions}
    gone = await build_candidate_sets(gap_result=gap, retrieval_service=retrieval, catalog=catalog, consumed_session_ids=everything)
    assert all(r.resource_id != res.resource_id for cs in gone.values() for r in cs.resources), "a finished resource is not offered again"


# -- H. LLM failure -> the fallback planner is not thin ------------------------------------------------------------------


async def test_h_when_the_llm_output_is_unusable_the_fallback_planner_still_fills_a_large_budget(catalog_session, graph_service):
    d = await _run_graph(catalog_session, graph_service, PlannerAgent(ScriptedLLM(["not json"] * 6)), hours=12)
    assert d["final_degraded"] is True
    items = d["final_items"]
    ratio = sum(i.est_minutes for i in items) / d["hours_budget_minutes"]
    assert 0.6 <= ratio <= 0.8, ratio
    assert _validate(d, items, graph_service).passed
    await _assert_sessions_are_real(catalog_session, items)
    assert all(i.reason.graph_path for i in items), "deterministic ID provenance on every item"


async def test_the_fallback_is_valid_and_bounded_at_small_medium_and_large_budgets(catalog_session, graph_service):
    totals = {}
    for hours in (2, 5, 10, 20):
        d = await _run_graph(catalog_session, graph_service, PlannerAgent(LLMGateway()), hours=hours)  # provider none -> fallback
        items = d["final_items"]
        assert _validate(d, items, graph_service).passed, hours
        await _assert_sessions_are_real(catalog_session, items)
        totals[hours] = sum(i.est_minutes for i in items)
        assert totals[hours] <= d["hours_budget_minutes"]
    assert totals[2] <= totals[5] <= totals[10] <= totals[20]
    assert totals[10] >= 5 * 60 * 0.6, "a 10 h week is no longer a ~1 h plan"  # thin-plan regression guard (was 65-95 min)


# -- I / M-analog. the model selects real sessions; code owns durations, validates, and tops up --------------------------------


def _picks(sets, *, sessions_per_objective: int = 2, objectives: int = 3, **overrides):
    items, day = [], 1
    lessons = sorted((cs for cs in sets.values() if cs.objective_type == "lesson" and cs.resources), key=lambda c: -c.priority)
    for cs in lessons[:objectives]:
        res = cs.resources[0]
        for sess in res.sessions[:sessions_per_objective]:
            items.append({
                "type": "resource", "objective_id": cs.objective_id, "skill_id": cs.skill_id, "resource_id": res.resource_id,
                "session_id": sess.session_id, "practice_item_ids": [], "est_minutes": 999, "difficulty": 1, "day_slot": day,
                "depends_on": [], "reason_text": "Because this is your highest-priority gap.", **overrides,
            })
        day = min(day + 1, 5)
    return items


async def _sets_for(catalog_session, graph_service, hours=12, cap=45):
    catalog = CatalogRepository(catalog_session)
    retrieval = ResourceRetrievalService(catalog, graph_service, DegradedEmbeddingGateway())
    return await build_candidate_sets(gap_result=analyze_gaps(ROLE, [], [], graph_service), retrieval_service=retrieval, catalog=catalog, session_cap_minutes=cap)


async def test_a_valid_model_draft_of_real_sessions_is_accepted_topped_up_and_never_falls_back(catalog_session, graph_service):
    sets = await _sets_for(catalog_session, graph_service)
    draft = json.dumps({"items": _picks(sets), "overall_reason": "Start with your biggest gaps."})
    llm = ScriptedLLM([draft])
    d = await _run_graph(catalog_session, graph_service, PlannerAgent(llm), hours=12)

    assert d["final_degraded"] is False and llm.calls == 1, "accepted first time, no extra LLM call for the top-up"
    items = d["final_items"]
    assert _validate(d, items, graph_service).passed
    await _assert_sessions_are_real(catalog_session, items)
    # the model's own picks kept their durations from code, not the bogus 999
    assert all(i.est_minutes <= 45 for i in items)
    assert d["topup_items"] > 0 and d["topup_minutes"] > 0
    assert sum(i.est_minutes for i in items) <= 0.80 * d["hours_budget_minutes"] + 1e-9
    assert "added automatically" in d["final_overall_reason"] and d["final_overall_reason"].startswith("Start with your biggest gaps.")
    # the top-up continues objectives the model chose; it never introduces a skill
    chosen_skills = {p["skill_id"] for p in _picks(sets)}
    assert {i.skill_id for i in items} == chosen_skills
    assert all(i.reason.graph_path for i in items)


async def test_i_a_model_that_invents_a_session_is_rejected_and_the_fallback_takes_over(catalog_session, graph_service):
    sets = await _sets_for(catalog_session, graph_service)
    bad_sessions = json.dumps({"items": _picks(sets, session_id="res.made_up#1"), "overall_reason": "x"})
    invented_resource = json.dumps({"items": _picks(sets, resource_id="res.made_up", session_id=None), "overall_reason": "x"})
    llm = ScriptedLLM([bad_sessions] * 3 + [invented_resource] * 3)
    d = await _run_graph(catalog_session, graph_service, PlannerAgent(llm), hours=12)
    assert d["final_degraded"] is True, "an invented session/resource never reaches the plan"
    assert _validate(d, d["final_items"], graph_service).passed
    await _assert_sessions_are_real(catalog_session, d["final_items"])


async def test_j_a_model_that_repeats_or_skips_a_session_fails_validation_then_falls_back(catalog_session, graph_service):
    sets = await _sets_for(catalog_session, graph_service)
    picks = _picks(sets, sessions_per_objective=2, objectives=1)
    repeated = json.dumps({"items": [picks[0], dict(picks[0])], "overall_reason": "x"})
    skipping = json.dumps({"items": [dict(picks[0], session_id=picks[0]["resource_id"] + "#3")], "overall_reason": "x"})
    for draft in (repeated, skipping):
        d = await _run_graph(catalog_session, graph_service, PlannerAgent(ScriptedLLM([draft] * 3)), hours=12)
        assert d["final_degraded"] is True
        assert _validate(d, d["final_items"], graph_service).passed


# -- API: persistence, provenance, multi-week continuation -----------------------------------------------------------------


async def test_the_api_plan_carries_and_persists_session_provenance(app_client):
    persona = next(p for p in PERSONAS if p["id"] == "be-12h")
    plan, _ = await _plan_for(app_client, persona)
    with_session = [i for i in plan["items"] if i["resource_id"]]
    assert with_session and all(i["session"] and i["session"]["resource_id"] == i["resource_id"] for i in with_session)
    assert any(i["session"]["count"] > 1 for i in with_session), "a 12 h learner gets multi-session resources"
    assert all(i["reason"]["graph_path"] for i in plan["items"])
    assert sum(i["est_minutes"] for i in plan["items"]) / (persona["hours"] * 60 * 0.9) >= 0.6

    current = (await app_client.get("/api/learners/me/plans/current")).json()
    assert sorted((i["item_id"], (i["session"] or {}).get("session_id")) for i in current["items"]) == sorted(
        (i["item_id"], (i["session"] or {}).get("session_id")) for i in plan["items"]
    )


async def test_d_next_week_continues_finished_resources_through_the_api(app_client):
    persona = {"id": "multi-week", "role": ROLE, "hours": 6, "skills": []}
    week0, _ = await _plan_for(app_client, persona)
    week0_sessions = {i["session"]["session_id"]: i for i in week0["items"] if i["session"]}
    long_resources = {s["resource_id"] for s in (i["session"] for i in week0_sessions.values()) if s["count"] > s["index"]}
    assert long_resources, "week 0 leaves at least one long resource part-way through"

    async with SessionLocal() as session:  # the learner finishes everything scheduled in week 0
        await session.execute(update(m.PlanItem).where(m.PlanItem.session.is_not(None)).values(status="done"))
        await session.commit()

    week1 = (await app_client.post("/api/learners/me/plans", json={"week_index": 1})).json()
    week1_sessions = [i["session"] for i in week1["items"] if i["session"]]
    assert not ({s["session_id"] for s in week1_sessions} & set(week0_sessions)), "no finished session is offered again"
    for rid in long_resources:
        done = sorted(s["index"] for s in (i["session"] for i in week0_sessions.values()) if s["resource_id"] == rid)
        nxt = sorted(s["index"] for s in week1_sessions if s["resource_id"] == rid)
        if nxt:
            assert nxt[0] == done[-1] + 1, f"{rid}: week 1 continues at session {done[-1] + 1}"
    assert week1["items"], "the next week still has material"


async def test_planned_but_not_done_sessions_are_offered_again(app_client):
    persona = {"id": "not-done", "role": ROLE, "hours": 6, "skills": []}
    week0, _ = await _plan_for(app_client, persona)
    ids0 = {i["session"]["session_id"] for i in week0["items"] if i["session"]}
    week1 = (await app_client.post("/api/learners/me/plans", json={"week_index": 1})).json()
    ids1 = {i["session"]["session_id"] for i in week1["items"] if i["session"]}
    assert ids0 & ids1, "rolling horizon: what was planned but not completed is re-offered"


async def test_every_persona_plan_has_no_duplicate_sessions_and_valid_sessions(app_client):
    """Regression for the shared-resource duplicate: all ten evaluation personas, through the real API + fallback planner."""
    async with SessionLocal() as session:
        rows = {r.resource_id: r for r in (await session.execute(select(m.Resource))).scalars().all()}
    for persona in PERSONAS:
        plan, _ = await _plan_for(app_client, persona)
        ids = [i["session"]["session_id"] for i in plan["items"] if i["session"]]
        assert len(ids) == len(set(ids)), (persona["id"], sorted({x for x in ids if ids.count(x) > 1}))
        per_resource: dict[str, int] = {}
        for i in plan["items"]:
            if i["session"]:
                per_resource[i["resource_id"]] = per_resource.get(i["resource_id"], 0) + i["est_minutes"]
        for rid, minutes in per_resource.items():
            assert minutes <= rows[rid].duration_min, (persona["id"], rid)
