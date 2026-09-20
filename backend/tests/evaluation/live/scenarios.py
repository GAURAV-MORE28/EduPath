"""Scenario runners for the live LLM evaluation: one async function per *case*, grouped into areas
A-G (profiling, gap, planner, assessor, reflection, tutor, web search) plus vision and known-issue probes.

Every case drives the REAL app in-process (ASGI, in-memory SQLite, the live providers configured in `.env`) and
returns a `CaseOutcome`:

    metrics    numbers the report aggregates (None = not measurable for this case -> "N/A", never 0)
    checks     HARD invariants that the deterministic layer guarantees no matter what the model says
               (plans within budget, citations real, no forbidden skills...). A False here fails the case.
    fallback   True when a deterministic fallback replaced a model result (the model output was unusable)
    examples   small human-readable samples that accompany the aggregate numbers

Quality metrics are *reported*, they never fail a case; only `checks` do. Deterministic checks are preferred; the
one model-based signal (the Assessor's blind solver) is labelled as such in the report and is not ground truth.
"""
from __future__ import annotations

import json
import re
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import func, select

from app.planning.sessions import SessionizationPolicy, segment_durations
from tests.evaluation.live.instrument import CaseContext, current_case, redact, setup_mode
from tests.evaluation.metrics import load_gold

GOLD_LIVE = Path(__file__).parent / "gold_live.json"
CLOSED_OPERATOR_SET = {"INSERT_REMEDIATION", "DEFER", "REMOVE_DUPLICATE", "REPLACE_RESOURCE", "ADD_PROBE", "SPLIT_ACTIVITY"}
STOPWORDS = {"the", "and", "for", "with", "of", "to", "in", "on", "a", "an", "basics", "fundamentals", "intro", "using"}


def load_live_gold() -> dict[str, Any]:
    return json.loads(GOLD_LIVE.read_text(encoding="utf-8"))


@dataclass
class CaseOutcome:
    metrics: dict[str, Any] = field(default_factory=dict)
    checks: dict[str, bool] = field(default_factory=dict)
    fallback: bool | None = None
    schema_valid: bool | None = None
    validator_pass: bool | None = None
    examples: list[Any] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class EvalState:
    suite: str
    app: Any
    graph: Any
    resources: dict[str, Any]
    resource_targets: dict[str, set[str]]
    skills: dict[str, Any]
    misconceptions: list[Any]
    gold: dict[str, Any]
    profiled: dict[str, dict[str, Any]] = field(default_factory=dict)
    plans: list[dict[str, Any]] = field(default_factory=list)
    web_urls: set[str] = field(default_factory=set)
    tutor_learner: dict[str, Any] | None = None
    resource_count_at_start: int = 0

    @asynccontextmanager
    async def client(self, cookie: str):
        transport = httpx.ASGITransport(app=self.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test", cookies={"session": cookie}, timeout=240.0) as c:
            yield c


def _rate(num: float, den: float) -> float | None:
    return None if not den else num / den


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", text.lower()) if len(t) >= 3 and t not in STOPWORDS}


async def _fetch_run(client: httpx.AsyncClient, run_id: str | None) -> dict[str, Any] | None:
    if not run_id:
        return None
    resp = await client.get(f"/api/runs/{run_id}")
    return resp.json() if resp.status_code == 200 else None


def _intake(role: str, hours: float, skills: list[str], modality: list[str] | None = None, session: int = 45) -> dict[str, Any]:
    return {
        "current_skills": skills, "experience_summary": "", "target_role_id": role, "career_goal": "", "weekly_hours": hours,
        "preferences": {"modality_order": modality or ["do", "watch", "read"], "language": "en", "session_length_min": session},
    }


# ====================================================================================================================
# A. PROFILING (+ evidence tier discipline, normalization, injection resistance)


async def case_profiling(st: EvalState, ctx: CaseContext, resume: dict[str, Any]) -> CaseOutcome:
    from app.profiling.pii import scrub_pii

    skills = st.skills
    out = CaseOutcome()
    async with st.client(f"live-prof-{resume['id']}") as c:
        assert (await c.post("/api/learners", json=_intake("role.ml_engineer", 6, []))).status_code == 201
        up = await c.post("/api/learners/me/documents", files={"file": (f"{resume['id']}.md", resume["text"].encode(), "text/markdown")})
        if up.status_code != 200:
            raise RuntimeError(f"upload -> {up.status_code}: {redact(up.text)}")
        summary = up.json()["claims_summary"]
        claims = (await c.get("/api/learners/me/claims/pending")).json()
        decisions = [{"claim_id": k["claim_id"], "action": "confirm" if k["normalized_skill_id"] else "remove"} for k in claims]
        confirm = await c.post("/api/learners/me/claims/confirm", json={"decisions": decisions})
        gaps = (await c.get("/api/learners/me/gaps")).json()
        profile = (await c.get("/api/learners/me/profile")).json()

    scrubbed = scrub_pii(resume["text"])[0]
    got = {k["normalized_skill_id"] for k in claims if k["normalized_skill_id"]}
    expected, forbidden = set(resume["expected"]), set(resume["forbidden"])
    tp, fp, fn = len(got & expected), len(got - expected), len(expected - got)

    def supports(claim) -> bool:
        skill = skills.get(claim["normalized_skill_id"])
        low = claim["verbatim_span"].lower()
        return skill is not None and any(p.strip().lower() in low for p in (skill.label, *skill.aliases) if p.strip())

    mapped = [k for k in claims if k["normalized_skill_id"]]
    unsupported = [k for k in mapped if not supports(k)]
    norm = lambda t: re.sub(r"\s+", " ", t).strip().lower()  # noqa: E731 -- the verifier's own comparison (whitespace/case-insensitive)
    span_ok = sum(scrubbed[k["span_offsets"]["start"]:k["span_offsets"]["end"]] == k["verbatim_span"] for k in claims)  # exact offsets
    span_present = sum(norm(k["verbatim_span"]) in norm(scrubbed) for k in claims)  # the quoted span really is in the document
    conf_right = [k["normalization_confidence"] for k in mapped if k["normalized_skill_id"] in expected]
    conf_wrong = [k["normalization_confidence"] for k in mapped if k["normalized_skill_id"] not in expected]
    tiers: dict[str, int] = {}
    for k in claims:
        tiers[k["tier"]] = tiers.get(k["tier"], 0) + 1
    methods: dict[str, int] = {}
    for k in claims:
        methods[k["normalization_method"]] = methods.get(k["normalization_method"], 0) + 1

    out.fallback = bool(summary["degraded"])
    out.schema_valid = not summary["degraded"]  # the Profiler falls back only when no valid JSON survived its retries
    out.validator_pass = summary["dropped_unverified"] == 0
    out.metrics = {
        "tp": tp, "fp": fp, "fn": fn, "expected_n": len(expected), "claims": len(claims), "mapped_claims": len(mapped),
        "extracted": summary["extracted"], "dropped_unverified": summary["dropped_unverified"],
        "dropped_injection": summary["dropped_injection"], "unsupported_claims": len(unsupported),
        "span_fidelity_ok": span_ok, "span_present_ok": span_present, "forbidden_hits": len(got & forbidden), "first_try_schema_valid": (not summary["degraded"]) and ctx.agent_retries == 0,
        "conf_right": conf_right, "conf_wrong": conf_wrong, "tiers": tiers, "methods": methods,
        "precision": _rate(tp, tp + fp), "recall": _rate(tp, tp + fn),
    }
    out.checks = {
        "no_forbidden_skill_committed": not (got & forbidden),
        "verbatim_span_present_in_source": span_present == len(claims),
        "resume_alone_never_above_E1": set(tiers) <= {"E0", "E1"},
        "confirmation_succeeded": confirm.status_code == 200,
    }
    out.examples = [{
        "resume": resume["id"], "expected": sorted(expected), "got": sorted(got),
        "missed": sorted(expected - got), "extra": sorted(got - expected),
        "sample_claim": (mapped[0]["skill_label"], mapped[0]["verbatim_span"][:80], mapped[0]["normalized_skill_id"]) if mapped else None,
    }]
    st.profiled[resume["id"]] = {"got": got, "expected": expected, "gaps": gaps, "role": profile["target_role_id"]}
    return out


# ====================================================================================================================
# B. GAP ANALYSIS (deterministic engine, fed by live profiling)


async def case_gap(st: EvalState, ctx: CaseContext, resume_id: str) -> CaseOutcome:
    """The Gap Engine contains no LLM. What the live stack can change is its *input*: this case measures how
    live-profiling errors propagate into gap output, holding the evidence tier fixed (E1) so that only skill
    identification differs between the live-derived learner and the gold learner."""
    from app.gap.engine import LearnerSkillRecord, analyze_gaps

    data = st.profiled.get(resume_id)
    if data is None:
        raise RuntimeError("profiling case did not complete; gap propagation not measurable")
    role = data["role"]

    def report(skill_ids: set[str]):
        recs = [LearnerSkillRecord(skill_id=s, alpha=1.0, beta=1.5, tier_max="E1", n_obs=0) for s in skill_ids]
        return analyze_gaps(role, recs, [], st.graph)

    live, gold = report(data["got"]), report(data["expected"])

    def statuses(r) -> dict[str, str]:
        s = {g.skill_id: g.status for g in r.gaps}
        s.update({x.skill_id: "MET" for x in r.strengths})
        return s

    sl, sg = statuses(live), statuses(gold)
    shared = sorted(set(sl) & set(sg))
    agree = sum(sl[s] == sg[s] for s in shared)
    coverage_agree = sum((sl[s] == "MISSING") == (sg[s] == "MISSING") for s in shared)
    gaps_live = {s for s, v in sl.items() if v != "MET"}
    gaps_gold = {s for s, v in sg.items() if v != "MET"}
    top = lambda r: [g.skill_id for g in sorted(r.gaps, key=lambda g: (-g.priority, g.skill_id))[:5]]  # noqa: E731
    top_live, top_gold = top(live), top(gold)

    # invariants on the API report the live-profiled learner actually received (real tiers, real state)
    api = data["gaps"]
    layer = {g["skill_id"]: g["ordering_layer"] for g in api["gaps"] if g["ordering_layer"] >= 0}
    order_violations = sum(1 for e in api["prerequisite_edges"] if e["from_skill_id"] in layer and e["to_skill_id"] in layer and layer[e["from_skill_id"]] > layer[e["to_skill_id"]])
    unverified = {g["skill_id"] for g in api["gaps"] if g["status"] == "UNVERIFIED"}
    probe_obj = {o["skill_id"] for o in api["objectives"] if o["objective_type"] == "probe"}

    out = CaseOutcome()
    out.metrics = {
        "status_pairs": len(shared), "status_agree": agree, "coverage_pairs": len(shared), "coverage_agree": coverage_agree,
        "gap_intersection": len(gaps_live & gaps_gold), "gap_union": len(gaps_live | gaps_gold),
        "top5_overlap": len(set(top_live) & set(top_gold)), "top5_n": len(top_gold),
        "required_skills": len(shared), "gaps_live": len(gaps_live), "gaps_gold": len(gaps_gold),
        "api_objectives": len(api["objectives"]), "prereq_order_violations": order_violations,
    }
    out.checks = {
        "statuses_in_closed_set": {g["status"] for g in api["gaps"]} <= {"MET", "WEAK", "UNVERIFIED", "MISSING", "BLOCKED"},
        "prerequisite_consistency": order_violations == 0,
        "verify_before_teach": unverified <= probe_obj,
    }
    out.notes.append("Gap Engine is deterministic (no LLM): measures propagation of live-profiling errors, tier held at E1")
    out.examples = [{"resume": resume_id, "live_only_gaps": sorted(gaps_live - gaps_gold)[:5], "gold_only_gaps": sorted(gaps_gold - gaps_live)[:5]}]
    return out


# ====================================================================================================================
# C. PLANNER


async def case_planner(st: EvalState, ctx: CaseContext, persona: dict[str, Any]) -> CaseOutcome:
    out = CaseOutcome()
    async with st.client(f"live-plan-{persona['id']}") as c:
        body = _intake(persona["role"], persona["hours"], persona["skills"], persona.get("modality"), persona.get("session", 45))
        assert (await c.post("/api/learners", json=body)).status_code == 201
        resp = await c.post("/api/learners/me/plans", json={})
        if resp.status_code != 200:
            raise RuntimeError(f"POST /plans -> {resp.status_code}: {redact(resp.text)}")
        plan = resp.json()  # response_model-validated by the API: parsing succeeded == schema-valid
        gaps = (await c.get("/api/learners/me/gaps")).json()
        run = await _fetch_run(c, resp.headers.get("x-run-id"))

    items, budget = plan["items"], persona["hours"] * 60
    total = sum(i["est_minutes"] for i in items)
    rejected = [s for s in (run or {}).get("steps", []) if s["actor"] == "Plan Validator" and s["status"] == "degraded"]  # a rejected LLM draft
    planner_loops = (run or {}).get("planner_loops")

    status = {g["skill_id"]: g["status"] for g in gaps["gaps"]}
    day: dict[str, int] = {}
    unknown = broken = misaligned = blocked = with_res = provenance = reason_text = dupes = 0
    seen_pairs: set[tuple] = set()
    cap = persona.get("session", 45)
    policy = SessionizationPolicy.for_learner(cap)
    with_session = session_bad = session_dupes = 0
    session_ids: set[str] = set()
    consumed: dict[str, int] = {}
    session_problems: list[str] = []
    for it in items:
        day[it["skill_id"]] = min(day.get(it["skill_id"], it["day_slot"]), it["day_slot"])
        blocked += status.get(it["skill_id"]) == "BLOCKED"
        sess = it.get("session")
        pair = (it["skill_id"], it["resource_id"], it["type"], (sess or {}).get("session_id"))  # a *session* repeated is the duplicate
        dupes += pair in seen_pairs
        seen_pairs.add(pair)
        r = it["reason"]
        provenance += bool(r.get("graph_path") or r.get("evidence_ids") or r.get("decision_id"))
        reason_text += bool(r.get("text", "").strip())
        if it["resource_id"]:
            with_res += 1
            row = st.resources.get(it["resource_id"])
            unknown += row is None
            broken += row is not None and row.link_status != "ok"
            misaligned += it["skill_id"] not in st.resource_targets.get(it["resource_id"], set())
            # Stage 2: recompute the session from the raw catalog row, independently of the planner's own code
            if sess is None:
                session_bad += 1
                session_problems.append(f"{it['resource_id']}: no session provenance")
            elif row is not None:
                with_session += 1
                parts = segment_durations(row.duration_min, policy)
                idx = sess.get("index", 0)
                ok = (
                    sess["resource_id"] == row.resource_id and sess["session_id"] == f"{row.resource_id}#{idx}"
                    and sess["count"] == len(parts) and 1 <= idx <= len(parts) and sess["resource_duration_min"] == row.duration_min
                    and it["est_minutes"] == parts[idx - 1] and it["est_minutes"] <= cap
                    and sess["label"] == (row.title if len(parts) == 1 else f"{row.title} — Study Segment {idx} of {len(parts)}")
                )
                if not ok:
                    session_bad += 1
                    session_problems.append(f"{sess['session_id']}: does not match the catalog-derived session")
                if sess["session_id"] in session_ids:
                    session_dupes += 1
                session_ids.add(sess["session_id"])
                consumed[row.resource_id] = consumed.get(row.resource_id, 0) + it["est_minutes"]
    over_consumed = sum(1 for rid, mins in consumed.items() if st.resources[rid].duration_min < mins)
    topup_items = topup_min = 0
    for step in (run or {}).get("steps", []):
        if step["actor"] == "Plan Filler" and str(step.get("output_ref", "")).startswith("topup="):
            n, mins = str(step["output_ref"])[len("topup="):].split("/")
            topup_items, topup_min = int(n), int(mins)
    order_violations = sum(
        1 for e in gaps["prerequisite_edges"]
        if e["from_skill_id"] in day and e["to_skill_id"] in day and day[e["from_skill_id"]] > day[e["to_skill_id"]]
    )
    objective_ids = [o["objective_id"] for o in gaps["objectives"]]
    plan_objectives = {i["objective_id"] for i in items}
    top10 = objective_ids[:10]

    out.fallback = bool(plan["degraded"])
    out.schema_valid = True
    out.validator_pass = not plan["degraded"]  # committed straight from the LLM draft == the deterministic validator accepted it
    out.metrics = {
        "hours": persona["hours"], "budget_min": budget, "scheduled_min": total, "utilization": _rate(total, budget),
        "utilization_effective": _rate(total, budget * 0.9),  # of hours*60*0.9, the planner's own budget (design 16.3)
        "items": len(items), "items_with_resource": with_res,
        "items_with_session": with_session, "session_problems": session_bad, "duplicate_sessions": session_dupes,
        "resources_over_consumed": over_consumed, "distinct_resources": len(consumed),
        "topup_items": topup_items, "topup_min": topup_min, "model_selected_min": total - topup_min,
        "first_attempt_pass": (not plan["degraded"]) and (planner_loops in (None, 1)),
        "planner_loops": planner_loops, "validator_rejections": len(rejected),
        "objectives_total": len(objective_ids), "objectives_covered": len(plan_objectives & set(objective_ids)),
        "top10_total": len(top10), "top10_covered": len(plan_objectives & set(top10)),
        "aligned_resources": with_res - misaligned, "items_with_id_provenance": provenance, "items_with_reason_text": reason_text,
        "overall_reason_present": bool(plan["overall_reason"].strip()), "duplicate_items": dupes,
        "max_item_min": max((i["est_minutes"] for i in items), default=0), "session_cap_min": cap,
        "days_used": len({i["day_slot"] for i in items}),
        "under_filled_50pct": total < 0.5 * budget,
    }
    out.checks = {
        "within_time_budget": total <= budget,
        "sessions_are_real_valid_and_within_cap": session_bad == 0 and over_consumed == 0,
        "no_duplicate_sessions": session_dupes == 0,
        "every_resource_exists_and_is_healthy": unknown == 0 and broken == 0,
        "resource_targets_the_scheduled_skill": misaligned == 0,
        "no_blocked_skill_scheduled": blocked == 0,
        "prerequisite_order": order_violations == 0,
        "non_empty_week": bool(items),
    }
    out.examples = [{
        "persona": persona["id"], "hours": persona["hours"], "utilization": f"{total}/{budget} min",
        "session_problems": session_problems[:3], "topup": f"{topup_items} items / {topup_min} min",
        "degraded(fallback)": plan["degraded"], "validator_rejections": [s["output_ref"] for s in rejected],
        "first_items": [(i["type"], i["skill_id"], i["resource_id"], i["est_minutes"], i["day_slot"]) for i in items[:3]],
        "reason": plan["overall_reason"][:160],
    }]
    st.plans.append({"persona": persona["id"], "plan": plan})
    return out


# ====================================================================================================================
# D. ASSESSMENT (generated MCQs)

_ALL_NONE = re.compile(r"\b(all|none) of the above\b", re.IGNORECASE)


def _grade_item(draft, skill, allowed_misconceptions: set[str]) -> dict[str, bool]:
    """Deterministic rubric for one generated MCQ. Structure is already enforced by the parser; these are the
    things a parser cannot know."""
    texts = [o.text.strip().lower() for o in draft.options]
    distractors = [o for o in draft.options if not o.is_key]
    key = next(o for o in draft.options if o.is_key)
    d_len = [len(o.text) for o in distractors] or [0]
    body = " ".join([draft.question, *[o.text for o in draft.options], draft.explanation])
    label_tokens = _tokens(skill.label) | {t for a in skill.aliases for t in _tokens(a)}
    explanation_words = len(draft.explanation.split())
    return {
        "exactly_one_key": sum(o.is_key for o in draft.options) == 1,
        "options_3_to_5": 3 <= len(draft.options) <= 5,
        "options_distinct": len(set(texts)) == len(texts),
        "no_all_or_none_of_the_above": not any(_ALL_NONE.search(t) for t in texts),
        "no_length_cue": len(key.text) <= 1.6 * (sum(d_len) / len(d_len)) + 12,
        "distractors_differ_from_key": all(o.text.strip().lower() != key.text.strip().lower() for o in distractors),
        "tags_are_catalogued": all(o.misconception_id in allowed_misconceptions for o in distractors if o.misconception_id),
        "key_untagged": key.misconception_id is None,
        "explanation_present": explanation_words >= 4 and draft.explanation.strip().lower() != draft.question.strip().lower(),
        "skill_aligned": bool(label_tokens & _tokens(body)),
    }


async def case_assessor(st: EvalState, ctx: CaseContext, skill_id: str) -> CaseOutcome:
    from app.agents.assessor import AssessorAgent
    from app.gateway.llm_gateway import LLMGateway

    skill = st.skills[skill_id]
    mcs = [m for m in st.misconceptions if m.skill_id == skill_id]
    allowed = {m.misconception_id for m in mcs}
    agent = AssessorAgent(LLMGateway())
    drafts, degraded = await agent._generate(  # the exact generation path AssessorAgent.run() uses
        skill.label, skill.description, "intermediate",
        [{"misconception_id": m.misconception_id, "description": m.description} for m in mcs], 3,
    )
    out = CaseOutcome(fallback=degraded, schema_valid=not degraded)
    solved = []
    for d in drafts:
        solved.append(await agent._blind_solve_validate(d))  # model-based agreement, NOT ground truth
    rubric = [_grade_item(d, skill, allowed) for d in drafts]
    names = sorted(rubric[0]) if rubric else []
    per_check = {n: sum(r[n] for r in rubric) for n in names}
    distractors = [o for d in drafts for o in d.options if not o.is_key]
    stems = [d.question.strip().lower() for d in drafts]
    key_pos = [d.key_index for d in drafts]
    out.validator_pass = bool(drafts) and all(solved)  # the Assessor's own gate is the blind solver; the rubric below is a *quality* score
    out.metrics = {
        "requested": 3, "generated": len(drafts), "first_try_schema_valid": (not degraded) and ctx.agent_retries == 0,
        "blind_solver_agree": sum(solved), "blind_solver_n": len(solved),
        "rubric_checks_passed": sum(per_check.values()), "rubric_checks_total": len(rubric) * len(names), "per_check": per_check,
        "distractors": len(distractors), "distractors_tagged": sum(1 for o in distractors if o.misconception_id),
        "candidate_misconceptions": len(allowed), "distinct_stems": len(set(stems)), "key_positions": key_pos,
        "difficulties": [d.difficulty for d in drafts],
    }
    out.checks = {"tags_only_from_catalogue": all(r["tags_are_catalogued"] for r in rubric), "single_key_per_item": all(r["exactly_one_key"] for r in rubric)}
    if drafts:
        d0 = drafts[0]
        out.examples = [{"skill": skill_id, "question": d0.question[:200], "options": [(o.text[:70], "KEY" if o.is_key else o.misconception_id) for o in d0.options],
                         "explanation": d0.explanation[:160], "blind_solver_agrees": solved[0]}]
    if not drafts:
        out.notes.append("no items generated (agent degraded after retries)")
    return out


# ====================================================================================================================
# E. REFLECTION


async def _wrong_picks_for(st: EvalState, mc) -> list[tuple[str, int]]:
    from app.db.session import SessionLocal
    from app.repositories.catalog_repository import CatalogRepository

    picks: list[tuple[str, int]] = []
    async with SessionLocal() as session:
        catalog = CatalogRepository(session)
        for skill_id in dict.fromkeys([mc.skill_id, mc.root_skill_id]):
            for item in await catalog.get_practice_items_for_skill(skill_id, purpose="practice"):
                for idx, opt in enumerate(item.options):
                    if not opt["is_key"] and opt["misconception_id"] == mc.misconception_id:
                        picks.append((item.item_id, idx))
                        break
    return picks


async def reflection_cases(st: EvalState) -> list:
    out = []
    for mc in st.misconceptions:
        picks = await _wrong_picks_for(st, mc)
        if len(picks) >= 2:  # enough distinct tagged wrong answers to *confirm* the misconception
            out.append((mc, picks[:3]))
    return sorted(out, key=lambda t: t[0].misconception_id)


async def _struggle_submission(st: EvalState, cookie: str, mc, picks, *, skills: list[str] | None = None, hours: float = 6):
    """A fresh learner plans a week (setup: deterministic planner, no quota), then submits the planted wrong answers.
    The submission -- struggle detection -> Reflection Agent -> validation -> plan revision -- is the live part."""
    from app.db import models as m
    from app.db.session import SessionLocal

    async with st.client(cookie) as c:
        assert (await c.post("/api/learners", json=_intake("role.ml_engineer", hours, skills or []))).status_code == 201
        with setup_mode():
            assert (await c.post("/api/learners/me/plans", json={})).status_code == 200
        learner_id = (await c.get("/api/learners/me/profile")).json()["learner_id"]
        async with SessionLocal() as session:
            ps = m.PracticeSession(learner_id=learner_id, skill_id=mc.skill_id, purpose="practice", item_ids=[i for i, _ in picks])
            session.add(ps)
            await session.commit()
            set_id = ps.set_id
        resp = await c.post(f"/api/practice/{set_id}/submit", json={"answers": [{"item_id": i, "chosen_option": k} for i, k in picks]})
        plan_after = await c.get("/api/learners/me/plans/current")
        run = await _fetch_run(c, resp.headers.get("x-run-id"))
    return resp, learner_id, plan_after, run


async def case_reflection(st: EvalState, ctx: CaseContext, spec: tuple) -> CaseOutcome:
    from app.db import models as m
    from app.db.session import SessionLocal

    mc, picks = spec
    resp, learner_id, plan_after, run = await _struggle_submission(st, f"live-refl-{mc.misconception_id}", mc, picks)
    if resp.status_code != 200:
        raise RuntimeError(f"submit -> {resp.status_code}: {redact(resp.text)}")
    refl = resp.json()["reflection"]
    out = CaseOutcome()
    if refl is None:
        out.metrics = {"reflected": False}
        out.checks = {"reflection_triggered": False}
        return out

    ops = refl["operators"]
    op_names = {o["op"] for o in ops}
    graph = st.graph
    root = refl["root_cause_skill_id"]
    connected = root is not None and (root == mc.skill_id or root in graph.hard_ancestors(mc.skill_id))
    catalogued_remedies = set(mc.remediation_candidates or []) | {r for r, ts in st.resource_targets.items() if mc.root_skill_id in ts or mc.skill_id in ts}
    grounded_resources = [r for r in refl["remediation_resource_ids"] if r in catalogued_remedies]
    async with SessionLocal() as session:
        decision = await session.get(m.DecisionRecord, refl["decision_id"]) if refl["decision_id"] else None
        signals = set((await session.execute(select(m.StruggleSignal.signal_id).where(m.StruggleSignal.learner_id == learner_id))).scalars().all())
        assessments = set((await session.execute(select(m.Assessment.assessment_id).where(m.Assessment.learner_id == learner_id))).scalars().all())
    ev_ids = list(decision.evidence_ids or []) if decision else []
    known_ev = signals | assessments | {i for i, _ in picks}  # Reflection cites the learner's own assessed practice-item ids
    explanation = refl["explanation"].lower()
    concept_tokens = _tokens(st.skills[mc.root_skill_id].label) | _tokens(st.skills[mc.skill_id].label) | _tokens(mc.description)

    plan_json = plan_after.json() if plan_after.status_code == 200 else {"items": []}
    plan_total = sum(i["est_minutes"] for i in plan_json["items"])
    resources_ok = all(i["resource_id"] is None or i["resource_id"] in st.resources for i in plan_json["items"])

    out.fallback = bool(refl["degraded"])
    out.schema_valid = not refl["degraded"]  # a degraded outcome = the agent's draft was unusable/rejected; deterministic policy decided
    out.validator_pass = (not refl["degraded"]) and not refl["needs_attention"]
    out.metrics = {
        "root_correct": root == mc.root_skill_id, "misconception_correct": refl["misconception_id"] == mc.misconception_id,
        "root_connected": connected, "injected_root": mc.root_skill_id, "returned_root": root, "rounds": refl["rounds"],
        "ops": sorted(op_names), "closed_set": op_names <= CLOSED_OPERATOR_SET and bool(op_names),
        "remediation_resources": len(refl["remediation_resource_ids"]), "remediation_grounded": len(grounded_resources),
        "evidence_ids": len(ev_ids), "evidence_known": sum(e in known_ev for e in ev_ids),
        "explanation_names_concept": bool(concept_tokens & _tokens(explanation)),
        "explanation_words": len(refl["explanation"].split()),
        "first_try_schema_valid": (not refl["degraded"]) and ctx.agent_retries == 0,
    }
    out.checks = {
        "root_cause_is_graph_connected": connected,
        "operators_in_closed_set": op_names <= CLOSED_OPERATOR_SET and bool(op_names),
        "revision_committed_with_decision": bool(refl["plan_revision_id"] and refl["decision_id"]) and not refl["needs_attention"],
        "revised_plan_references_real_resources": resources_ok,
        "decision_has_evidence": bool(ev_ids),
    }
    out.examples = [{
        "misconception": mc.misconception_id, "injected_root": mc.root_skill_id, "returned_root": root, "ops": sorted(op_names),
        "degraded(deterministic policy)": refl["degraded"], "explanation": refl["explanation"][:220],
    }]
    return out


# ====================================================================================================================
# F. TUTOR

_ID_IN_TEXT = re.compile(r"\b(?:skill|res|misc|role|obj)\.[a-z0-9_.]+[a-z0-9]", re.IGNORECASE)


async def ensure_tutor_learner(st: EvalState) -> dict[str, Any]:
    """A learner with real history (evidence claims, a plan, a struggle -> reflection -> revision), built with the
    LLM refused (setup) so the Tutor is evaluated against state that does not depend on model luck."""
    if st.tutor_learner is not None:
        return st.tutor_learner
    g = st.gold["tutor_learner"]
    mc = next(m for m in st.misconceptions if m.misconception_id == g["misconception_id"])
    picks = (await _wrong_picks_for(st, mc))[:3]
    with setup_mode():
        resp, learner_id, _plan, _run = await _struggle_submission(st, "live-tutor-learner", mc, picks, skills=g["skills"], hours=g["hours"])
    refl = resp.json().get("reflection") if resp.status_code == 200 else None
    st.tutor_learner = {
        "cookie": "live-tutor-learner", "learner_id": learner_id,
        "decision_id": (refl or {}).get("decision_id"), "revision_id": (refl or {}).get("plan_revision_id"),
    }
    return st.tutor_learner


async def _real_ids(learner_id: str) -> set[str]:
    from app.db import models as m
    from app.db.session import SessionLocal

    async with SessionLocal() as session:
        ids: set[str] = set()
        for model, col, scoped in [
            (m.Skill, "skill_id", False), (m.Resource, "resource_id", False), (m.Misconception, "misconception_id", False),
            (m.Role, "role_id", False), (m.PracticeItem, "item_id", False), (m.Evidence, "evidence_id", True),
            (m.WeeklyPlan, "plan_id", True), (m.StruggleSignal, "signal_id", True), (m.DecisionRecord, "decision_id", True),
            (m.ReflectionRecord, "reflection_id", True), (m.Assessment, "assessment_id", True),
        ]:
            stmt = select(getattr(model, col))
            if scoped:
                stmt = stmt.where(model.learner_id == learner_id)
            ids |= set((await session.execute(stmt)).scalars().all())
        plan_ids = select(m.WeeklyPlan.plan_id).where(m.WeeklyPlan.learner_id == learner_id)
        ids |= set((await session.execute(select(m.PlanRevision.revision_id).where(m.PlanRevision.plan_id.in_(plan_ids)))).scalars().all())
        ids |= set((await session.execute(select(m.PlanItem.item_id).where(m.PlanItem.plan_id.in_(plan_ids)))).scalars().all())
        ids |= set((await session.execute(select(m.PlanItem.objective_id).where(m.PlanItem.plan_id.in_(plan_ids)))).scalars().all())
        return ids


async def case_tutor(st: EvalState, ctx: CaseContext, q: dict[str, Any]) -> CaseOutcome:
    tl = await ensure_tutor_learner(st)
    subst = {"@decision": tl["decision_id"], "@revision": tl["revision_id"]}
    hints = {k: subst.get(v, v) for k, v in (q.get("hints") or {}).items()}
    real = await _real_ids(tl["learner_id"])
    async with st.client(tl["cookie"]) as c:
        resp = await c.post("/api/learners/me/chat", json={"message": q["q"], **hints})
        if resp.status_code != 200:
            raise RuntimeError(f"chat -> {resp.status_code}: {redact(resp.text)}")
        run = await _fetch_run(c, resp.headers.get("x-run-id"))
    body = resp.json()
    answer, cites = body["answer"], body["citations"]
    kind = q["kind"]
    rejected = [s for s in (run or {}).get("steps", []) if s["actor"] == "Citation Verifier" and s["status"] == "degraded"]  # a rejected first draft
    compose_calls = [c for c in ctx.llm_calls if c.schema_name == "TutorAnswer" and not c.setup]
    ids_in_text = {i.lower() for i in _ID_IN_TEXT.findall(answer)}
    unreal_text_ids = sorted(i for i in ids_in_text if i not in {r.lower() for r in real})

    def resolve(x: str) -> str:
        return subst.get(x, x)

    expect_all = [resolve(x) for x in q.get("expect_cited", [])]
    expect_any = [resolve(x) for x in q.get("expect_cited_any", [])]
    prefixes = q.get("expect_cited_prefix", [])
    keywords = [k.lower() for k in q.get("expect_keywords", [])]
    forbidden = [x for x in q.get("forbidden_cited", [])]
    in_scope = kind not in {"oos", "adversarial"}

    invalid = [x for x in cites if x not in real]
    expectations: dict[str, bool] = {}
    if expect_all:
        expectations["cites_expected_ids"] = all(x in cites for x in expect_all)
    if expect_any:
        expectations["cites_one_of_expected"] = any(x in cites for x in expect_any)
    if prefixes:
        expectations["cites_expected_kind"] = any(x.startswith(tuple(prefixes)) for x in cites)
    if q.get("expect_min_citations"):
        expectations["has_citations"] = len(cites) >= q["expect_min_citations"]
    if keywords:
        expectations["answer_relevant_keyword"] = any(k in answer.lower() for k in keywords)

    out = CaseOutcome()
    out.fallback = bool(body["degraded"] or body["conservative"])
    out.schema_valid = not body["degraded"]
    out.validator_pass = (not rejected) and not body["degraded"]  # citations passed the deterministic verifier on the first draft
    out.metrics = {
        "kind": kind, "latency_in_case": True, "citations": len(cites), "invalid_final_citations": len(invalid),
        "first_draft_rejected": bool(rejected), "compose_calls": len(compose_calls), "degraded": body["degraded"],
        "conservative": body["conservative"], "expectations": expectations,
        "expectations_met": sum(expectations.values()), "expectations_total": len(expectations),
        "unreal_ids_in_text": len(unreal_text_ids), "answer_words": len(answer.split()), "in_scope": in_scope,
        "refused_or_conservative": (body["conservative"] or not cites) if not in_scope else None,
    }
    out.checks = {
        "final_citations_are_real_and_learner_scoped": not invalid,
        "no_adversary_supplied_id_cited": not any(f in cites for f in forbidden),
        "answer_is_non_empty": bool(answer.strip()),
    }
    if unreal_text_ids:
        out.notes.append(f"ids named in answer text but not in the database: {unreal_text_ids[:4]}")
    out.examples = [{"q": q["q"], "kind": kind, "citations": cites[:5], "conservative": body["conservative"],
                     "first_draft_rejected": bool(rejected), "answer": answer[:300]}]
    return out


# ====================================================================================================================
# G. WEB SEARCH


async def case_web(st: EvalState, ctx: CaseContext, skill_id: str) -> CaseOutcome:
    from app.db import models as m
    from app.db.session import SessionLocal
    from app.config import get_settings
    from app.gateway.web_fallback_gateway import DEFAULT_ALLOWED_DOMAINS, _is_allowed

    skill = st.skills[skill_id]
    configured = tuple(d.strip().lower() for d in get_settings().web_search_allowed_domains.split(",") if d.strip())
    allowed = configured or DEFAULT_ALLOWED_DOMAINS
    async with st.client("live-web-learner") as c:
        if (await c.get("/api/learners/me/profile")).status_code == 404:
            await c.post("/api/learners", json=_intake("role.ml_engineer", 6, []))
        resp = await c.get(f"/api/learners/me/skills/{skill_id}/web-resources")
    if resp.status_code != 200:
        raise RuntimeError(f"web-resources -> {resp.status_code}: {redact(resp.text)}")
    body = resp.json()
    results = body["results"]
    async with SessionLocal() as session:
        n_resources = (await session.execute(select(func.count()).select_from(m.Resource))).scalar_one()
    label_tokens = _tokens(skill.label) | {t for a in skill.aliases for t in _tokens(a)}
    hits = sum(bool(label_tokens & _tokens(r["title"] + " " + r["url"])) for r in results)
    domains = {re.sub(r"^www\.", "", (re.match(r"https?://([^/]+)", r["url"]) or [None, ""])[1]) for r in results}
    st.web_urls |= {r["url"] for r in results}

    out = CaseOutcome()
    out.fallback = not body["fetched"]
    out.metrics = {
        "fetched": body["fetched"], "results": len(results), "relevant_by_keyword": hits, "unique_domains": len(domains),
        "degraded_reason": body["degraded_reason"],
    }
    out.checks = {
        "all_https_and_allowlisted": all(_is_allowed(r["url"], allowed) for r in results),
        "all_marked_unvetted": all(r["curation_tier"] == "unvetted" for r in results),
        "no_catalog_id_on_web_results": all("resource_id" not in r for r in results),
        "catalog_not_mutated_by_search": n_resources == st.resource_count_at_start,
    }
    out.examples = [{"skill": skill_id, "titles": [r["title"][:70] for r in results[:3]], "domains": sorted(domains)[:4]}]
    return out


async def case_web_plan_exclusion(st: EvalState, ctx: CaseContext, _spec: Any) -> CaseOutcome:
    """Unvetted web URLs must never reach a plan: every scheduled resource_id is a catalog id and no plan item's
    catalog URL equals a web-search result URL."""
    catalog_urls = {r.url for r in st.resources.values()}
    plan_items = [i for p in st.plans for i in p["plan"]["items"]]
    scheduled = [i["resource_id"] for i in plan_items if i["resource_id"]]
    scheduled_urls = {st.resources[r].url for r in scheduled if r in st.resources}
    out = CaseOutcome()
    out.metrics = {"plans_checked": len(st.plans), "scheduled_resources": len(scheduled), "web_urls_seen": len(st.web_urls),
                   "web_urls_also_in_catalog": len(st.web_urls & catalog_urls)}
    out.checks = {
        "every_scheduled_resource_is_a_catalog_id": all(r in st.resources for r in scheduled),
        "no_web_result_url_in_any_plan": not (st.web_urls & scheduled_urls) or (st.web_urls & scheduled_urls) <= catalog_urls,
    }
    if not st.plans:
        out.notes.append("no plans available in this run; exclusion not measurable")
    return out


# ====================================================================================================================
# H. VISION (measures the known first-page-only limitation) and I. known-issue probes


def _image_only_pdf(pages: list[list[str]]) -> bytes:
    import pymupdf

    out = pymupdf.open()
    for lines in pages:
        tmp = pymupdf.open()
        page = tmp.new_page()
        for k, line in enumerate(lines):
            page.insert_text((72, 100 + 36 * k), line, fontsize=18)
        png = page.get_pixmap(dpi=110).tobytes("png")
        new = out.new_page(width=page.rect.width, height=page.rect.height)
        new.insert_image(new.rect, stream=png)  # a raster: there is no text layer to extract
    return out.tobytes()


async def case_vision(st: EvalState, ctx: CaseContext, _spec: Any) -> CaseOutcome:
    g = st.gold["vision"]
    pdf = _image_only_pdf([g["page1_text"], g["page2_text"]])
    async with st.client("live-vision") as c:
        assert (await c.post("/api/learners", json=_intake("role.ml_engineer", 6, []))).status_code == 201
        up = await c.post("/api/learners/me/documents", files={"file": ("scanned.pdf", pdf, "application/pdf")})
        if up.status_code != 200:
            raise RuntimeError(f"upload -> {up.status_code}: {redact(up.text)}")
        claims = (await c.get("/api/learners/me/claims/pending")).json()
    got = {k["normalized_skill_id"] for k in claims if k["normalized_skill_id"]}
    p1, p2 = set(g["page1_expected"]), set(g["page2_expected"])
    vlm = [p for p in ctx.provider_calls if p.provider == "vlm"]
    out = CaseOutcome()
    out.fallback = bool(up.json()["claims_summary"]["degraded"])
    llm_degraded = any(c.degraded for c in ctx.llm_calls if not c.setup)
    out.metrics = {
        "vlm_calls": len(vlm), "vlm_ok": sum(p.ok for p in vlm), "extraction_llm_degraded": llm_degraded, "page1_recall": _rate(len(got & p1), len(p1)),
        "page2_recall": _rate(len(got & p2), len(p2)), "pages_in_document": 2,
        "page1_hits": sorted(got & p1), "page2_hits": sorted(got & p2),
    }
    out.checks = {"vision_path_was_exercised": len(vlm) >= 1}
    out.notes.append("KNOWN LIMITATION probe: only page 1 of an image-only PDF is sent to the VLM; page-2 recall is expected to be 0")
    if llm_degraded:
        out.notes.append("the extraction LLM was unavailable, so claims came from the deterministic extractor over the VLM transcript; the VLM-side measurements (calls, page coverage) are unaffected")
    out.examples = [{"got": sorted(got), "page1": sorted(got & p1), "page2": sorted(got & p2)}]
    return out


async def case_auth_probe(st: EvalState, ctx: CaseContext, _spec: Any) -> CaseOutcome:
    """The session cookie is an unsigned string (known issue): anyone who presents the same value *is* that user."""
    async with st.client("victim-probe-user") as victim:
        await victim.post("/api/learners", json=_intake("role.ml_engineer", 6, ["Python"]))
        victim_profile = (await victim.get("/api/learners/me/profile")).json()
    async with st.client("victim-probe-user") as forger:  # a brand-new client that merely sends the same cookie value
        forged = await forger.get("/api/learners/me/profile")
    out = CaseOutcome()
    forgeable = forged.status_code == 200 and forged.json().get("learner_id") == victim_profile.get("learner_id")
    out.metrics = {"cookie_forgeable": forgeable}
    out.notes.append("KNOWN ISSUE (product/security): the `session` cookie is not signed; possession of a user id is authentication")
    return out
