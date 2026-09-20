"""Stage 2 planner behaviour over resource sessions (`docs/RESOURCE_SESSIONIZATION.md`), as pure functions on hand-built
fixtures -- no DB, gateway or LLM (same shape as `tests/test_plan_validator.py` / `tests/test_fallback_planner.py`).

Covers test-matrix rows C-G (one week / several weeks / several long resources / large & small budgets), I-J (invalid and
duplicate session candidates), K (resource-duration boundary), L (short-resource regression) and the parser/validator rules that
keep a model from inventing a session, a duration or a resource."""
from __future__ import annotations

import json

import pytest

from app.gap.engine import MET, MISSING, SkillGapEntry
from app.planning.candidates import ObjectiveCandidateSet, ResourceCandidateInfo
from app.planning.fallback import build_fallback_plan
from app.planning.fill import DayPlanner, attach_reason_provenance, extend_plan, summarize_utilization
from app.planning.prompting import PlannerParseError, build_planner_prompt, parse_planner_response
from app.planning.sessions import SessionizationPolicy, sessionize_resource
from app.planning.validator import V_SESSION, V_UTILIZATION, V_DUP, validate_plan
from app.schemas.common import PlanItem, PlanItemSession

BUDGET_20H = 20 * 60 * 0.9  # 1080
BUDGET_5H = 5 * 60 * 0.9  # 270
BUDGET_2H = 2 * 60 * 0.9  # 108


def _gap(skill_id: str, *, status: str = MISSING, layer: int = 0) -> SkillGapEntry:
    return SkillGapEntry(skill_id=skill_id, label=skill_id, status=status, gap_type=status.lower(), required_level=2, current_level=0, ordering_layer=layer)


def _res(resource_id: str, duration: int, *, cap: int = 45, score: float = 1.0, skill_id: str = "") -> ResourceCandidateInfo:
    policy = SessionizationPolicy(max_session_minutes=cap)
    return ResourceCandidateInfo(
        resource_id=resource_id, title=f"Title of {resource_id}", url=f"https://example.org/{resource_id}", type="course",
        duration_min=duration, modality="watch", score=score, score_breakdown={},
        sessions=sessionize_resource(resource_id=resource_id, title=f"Title of {resource_id}", duration_min=duration, policy=policy, skill_id=skill_id),
    )


def _cs(skill: str, resources: list[ResourceCandidateInfo], *, priority: float = 1.0, practice: list[str] | None = None) -> ObjectiveCandidateSet:
    return ObjectiveCandidateSet(
        objective_id=f"obj.{skill}", skill_id=f"skill.{skill}", objective_type="lesson", target_level=2, current_level=0,
        priority=priority, prerequisite_objective_ids=[], resources=resources, practice_item_ids=practice or [],
    )


def _plan(candidate_sets: dict[str, ObjectiveCandidateSet], budget: float, **kw) -> list[PlanItem]:
    gaps = {cs.skill_id: _gap(cs.skill_id) for cs in candidate_sets.values()}
    return build_fallback_plan(candidate_sets, gaps_by_skill=gaps, hours_budget_minutes=budget, **kw)


def _validate(items: list[PlanItem], candidate_sets: dict[str, ObjectiveCandidateSet], budget: float, **kw):
    gaps = {cs.skill_id: _gap(cs.skill_id) for cs in candidate_sets.values()}
    return validate_plan(
        items, candidate_sets=candidate_sets, gaps_by_skill=gaps, hard_prereqs_by_skill={}, hours_budget_minutes=budget,
        enforce_sessions=True, **kw,
    )


def _minutes(items: list[PlanItem]) -> int:
    return sum(i.est_minutes for i in items)


# -- L / A. short-resource regression: a complete short resource is still one item, whole, as before ------------------


def test_l_a_short_resource_is_scheduled_whole_exactly_as_before_with_its_practice_item():
    cs = _cs("a", [_res("res.short", 20)], practice=["item.1"])
    items = build_fallback_plan({cs.objective_id: cs}, gaps_by_skill={"skill.a": _gap("skill.a")}, hours_budget_minutes=100)
    assert [i.type for i in items] == ["resource", "practice"]
    assert items[0].est_minutes == 20 and items[0].session.count == 1 and items[0].session.label == "Title of res.short"
    assert items[1].practice_item_ids == ["item.1"]
    assert _validate(items, {cs.objective_id: cs}, 100).passed


# -- B/C. a long resource split across one week ---------------------------------------------------------------------


def test_c_a_long_resource_becomes_ordered_sessions_within_the_week():
    cs = _cs("a", [_res("res.long", 300)], practice=["item.1"])
    sets = {cs.objective_id: cs}
    items = _plan(sets, BUDGET_20H)
    sessions = [i for i in items if i.type == "resource"]
    assert [i.session.index for i in sessions] == list(range(1, 8))  # 300 min / 45 -> 7 sessions, all of them fit
    assert _minutes(sessions) == 300
    assert all(i.est_minutes <= 45 for i in sessions)
    days = [i.day_slot for i in sorted(sessions, key=lambda i: i.session.index)]
    assert days == sorted(days), "sessions stay in study order across the week"
    assert all(1 <= d <= 5 for d in days)
    assert _validate(items, sets, BUDGET_20H).passed


def test_c_practice_follows_the_last_study_session_of_its_skill():
    cs = _cs("a", [_res("res.long", 300)], practice=["item.1"])
    items = _plan({cs.objective_id: cs}, BUDGET_20H)
    practice = next(i for i in items if i.type == "practice")
    last = max((i for i in items if i.type == "resource"), key=lambda i: (i.day_slot, i.session.index))
    assert practice.day_slot >= last.day_slot and practice.depends_on == [last.item_id]


def test_c_a_budget_smaller_than_the_resource_schedules_only_a_leading_prefix_of_sessions():
    cs = _cs("a", [_res("res.long", 900)])
    items = _plan({cs.objective_id: cs}, BUDGET_5H)
    assert [i.session.index for i in items] == list(range(1, len(items) + 1))  # 1..n, never skipping
    assert _minutes(items) <= BUDGET_5H * 0.8 + 45  # stays at/below the acceptable-utilization ceiling (phase A may add the first unit)
    assert 0 < len(items) < 20


# -- D. multiple weeks: a resource continues where the last week stopped ---------------------------------------------


def test_d_a_later_week_continues_with_the_next_session_and_never_repeats_a_finished_one():
    full = _res("res.long", 300)
    week1 = _cs("a", [full])
    first_week = _plan({week1.objective_id: week1}, BUDGET_5H)
    done = {i.session.session_id for i in first_week}
    assert done and len(done) < len(full.sessions)

    remaining = tuple(s for s in full.sessions if s.session_id not in done)
    week2_res = ResourceCandidateInfo(**{**full.__dict__, "sessions": remaining})
    week2 = _cs("a", [week2_res])
    second_week = _plan({week2.objective_id: week2}, BUDGET_5H)

    got = [i.session.index for i in second_week]
    assert got[0] == len(done) + 1, "week 2 starts at the session after the last one finished"
    assert not ({i.session.session_id for i in second_week} & done), "no session is duplicated across weeks"
    assert _validate(second_week, {week2.objective_id: week2}, BUDGET_5H).passed
    # session numbering is stable: 'Study Segment 4 of 7' stays 4 of 7
    assert all(i.session.count == len(full.sessions) for i in second_week)


# -- E. multiple long resources ---------------------------------------------------------------------------------------


def test_e_several_long_resources_across_objectives_share_the_budget_without_new_skills_or_duplicates():
    sets = {
        f"obj.{n}": _cs(n, [_res(f"res.{n}", 360)], priority=10 - i) for i, n in enumerate(["a", "b", "c", "d", "e"])
    }
    items = _plan(sets, BUDGET_20H)
    skills = {i.skill_id for i in items}
    assert len(skills) == 3, "the 3-new-skill cap (V5) still bounds breadth; depth comes from sessions"
    assert skills == {"skill.a", "skill.b", "skill.c"}, "priority order decides which skills get the budget"
    ids = [i.session.session_id for i in items]
    assert len(ids) == len(set(ids))
    assert _validate(items, sets, BUDGET_20H).passed
    assert 0.7 <= _minutes(items) / BUDGET_20H <= 0.85


def test_e_one_objective_chains_its_next_ranked_resource_after_finishing_the_first():
    cs = _cs("a", [_res("res.one", 90), _res("res.two", 90), _res("res.three", 90), _res("res.four", 90)])
    items = _plan({cs.objective_id: cs}, BUDGET_20H)
    order = []
    for i in sorted(items, key=lambda i: (i.day_slot, i.session.index)):
        if i.resource_id not in order:
            order.append(i.resource_id)
    assert order == ["res.one", "res.two", "res.three"], "a resource is finished before the next starts, capped at 3 resources"
    assert "res.four" not in order


def test_e_phase_a_does_not_schedule_a_shared_resource_under_two_objectives():
    """Regression (found by the live evaluation, persona da-10h): one catalog resource can TARGET two skills, and the fallback's
    first pick for each objective was the same resource -> the same sessions studied twice under different objectives."""
    shared = _res("res.shared", 300)
    a = _cs("a", [shared], priority=2)
    b = _cs("b", [shared, _res("res.other", 100)], priority=1)
    items = _plan({a.objective_id: a, b.objective_id: b}, BUDGET_20H)
    ids = [i.session.session_id for i in items if i.session]
    assert len(ids) == len(set(ids)), ids
    assert {i.resource_id for i in items if i.objective_id == b.objective_id} == {"res.other"}
    only_shared = _cs("c", [shared], priority=0.5)
    sets = {a.objective_id: a, only_shared.objective_id: only_shared}
    items = _plan(sets, BUDGET_20H)
    assert {i.objective_id for i in items} == {a.objective_id}, "an objective whose only material is taken is skipped, not duplicated"
    assert _validate(items, sets, BUDGET_20H).passed


def test_e_a_resource_used_by_another_objective_is_not_reused_for_continuation():
    shared = _res("res.shared", 200)
    a = _cs("a", [_res("res.a", 45), shared], priority=2)
    b = _cs("b", [shared], priority=1)
    items = _plan({a.objective_id: a, b.objective_id: b}, BUDGET_20H)
    used_by = {}
    for i in items:
        used_by.setdefault(i.session.session_id, set()).add(i.objective_id)
    assert all(len(v) == 1 for v in used_by.values()), "the same session is never studied twice under two objectives"


# -- F / G. large and small budgets ----------------------------------------------------------------------------------


def test_f_a_large_budget_reaches_the_acceptable_utilization_without_exceeding_the_ceiling():
    sets = {f"obj.{n}": _cs(n, [_res(f"res.{n}", 600)], priority=3 - i) for i, n in enumerate("abc")}
    items = _plan(sets, BUDGET_20H)
    ratio = _minutes(items) / BUDGET_20H
    assert 0.70 <= ratio <= 0.80, ratio  # target 0.80 is a ceiling: Reflection keeps headroom
    assert _validate(items, sets, BUDGET_20H).passed


def test_g_a_small_budget_is_not_over_filled_and_still_valid():
    sets = {"obj.a": _cs("a", [_res("res.a", 600)]), "obj.b": _cs("b", [_res("res.b", 600)], priority=0.5)}
    items = _plan(sets, BUDGET_2H)
    assert _minutes(items) <= BUDGET_2H
    assert _validate(items, sets, BUDGET_2H).passed
    assert len(items) >= 1


def test_g_supply_limited_plans_stay_small_rather_than_being_padded():
    cs = _cs("a", [_res("res.tiny", 30)])
    items = _plan({cs.objective_id: cs}, BUDGET_20H)
    assert _minutes(items) == 30, "no other material exists for this objective: the plan is not padded"
    result = _validate(items, {cs.objective_id: cs}, BUDGET_20H)
    assert result.passed and not any(v.rule == V_UTILIZATION for v in result.soft_violations)


def test_more_budget_never_schedules_less_time():
    sets = {"obj.a": _cs("a", [_res("res.a", 600)]), "obj.b": _cs("b", [_res("res.b", 600)], priority=0.5)}
    totals = [_minutes(_plan(sets, hours * 54.0)) for hours in (2, 5, 10, 20)]
    assert totals == sorted(totals) and totals[-1] > 4 * totals[0]


# -- K. duration boundary ---------------------------------------------------------------------------------------------


def test_k_a_resource_exactly_at_the_cap_is_one_complete_session_and_one_minute_over_is_two():
    exact = _cs("a", [_res("res.exact", 45)])
    over = _cs("b", [_res("res.over", 46)])
    assert len(_plan({exact.objective_id: exact}, BUDGET_20H)) == 1
    two = _plan({over.objective_id: over}, BUDGET_20H)
    assert [i.est_minutes for i in two] == [23, 23] and _minutes(two) == 46


# -- I / J. invalid and duplicate sessions -----------------------------------------------------------------------------


def _item_for(cs: ObjectiveCandidateSet, session_index: int, *, day: int = 1, resource: int = 0, **override) -> PlanItem:
    res = cs.resources[resource]
    s = res.sessions[session_index - 1]
    base = dict(
        item_id=f"it{resource}{session_index}", type="resource", objective_id=cs.objective_id, skill_id=cs.skill_id, resource_id=res.resource_id,
        est_minutes=s.est_minutes, difficulty=1, day_slot=day,
        session=PlanItemSession(session_id=s.session_id, resource_id=s.resource_id, index=s.index, count=s.count, label=s.label,
                                start_min=s.start_min, end_min=s.end_min, resource_duration_min=s.resource_duration_min),
    )
    base.update(override)
    return PlanItem(**base)


def _rules(result) -> set[str]:
    return {v.rule for v in result.hard_violations}


def test_i_a_session_the_objective_does_not_offer_is_a_hard_violation():
    cs = _cs("a", [_res("res.a", 200)])
    bogus = _item_for(cs, 1).model_copy(update={"session": PlanItemSession(session_id="res.a#99", resource_id="res.a", index=99, count=99, label="x", start_min=0, end_min=1, resource_duration_min=200)})
    result = _validate([bogus], {cs.objective_id: cs}, BUDGET_20H)
    assert V_SESSION in _rules(result) and not result.passed


def test_i_a_session_id_from_a_different_resource_or_forged_metadata_is_rejected():
    cs = _cs("a", [_res("res.a", 200), _res("res.b", 200)])
    wrong_resource = _item_for(cs, 1).model_copy(update={"resource_id": "res.b"})  # session says res.a
    result = _validate([wrong_resource], {cs.objective_id: cs}, BUDGET_20H)
    assert V_SESSION in _rules(result)
    forged = _item_for(cs, 1)
    forged = forged.model_copy(update={"session": forged.session.model_copy(update={"label": "Chapter 1: Getting Started"})})
    assert V_SESSION in _rules(_validate([forged], {cs.objective_id: cs}, BUDGET_20H)), "an invented chapter title is caught"


def test_i_the_model_cannot_change_a_sessions_duration():
    cs = _cs("a", [_res("res.a", 200)])
    tampered = _item_for(cs, 1, est_minutes=5)
    assert V_SESSION in _rules(_validate([tampered], {cs.objective_id: cs}, BUDGET_20H))


def test_i_a_resource_item_without_session_provenance_fails_when_sessions_are_enforced_only():
    cs = _cs("a", [_res("res.a", 200)])
    bare = _item_for(cs, 1).model_copy(update={"session": None})
    assert V_SESSION in _rules(_validate([bare], {cs.objective_id: cs}, BUDGET_20H))
    # Reflection's patch validation (enforce_sessions defaults to False) keeps its permissive behaviour
    lenient = validate_plan([bare], candidate_sets={cs.objective_id: cs}, gaps_by_skill={"skill.a": _gap("skill.a")}, hard_prereqs_by_skill={}, hours_budget_minutes=BUDGET_20H)
    assert lenient.passed


def test_j_the_same_session_twice_is_a_duplicate():
    cs = _cs("a", [_res("res.a", 200)])
    dup = [_item_for(cs, 1), _item_for(cs, 1).model_copy(update={"item_id": "again", "day_slot": 2})]
    result = _validate(dup, {cs.objective_id: cs}, BUDGET_20H)
    assert {V_SESSION, V_DUP} & _rules(result) and not result.passed


def test_j_different_sessions_of_one_resource_are_not_a_duplicate():
    cs = _cs("a", [_res("res.a", 200)])
    items = [_item_for(cs, 1, day=1), _item_for(cs, 2, day=2), _item_for(cs, 3, day=3)]
    result = _validate(items, {cs.objective_id: cs}, BUDGET_20H)
    assert result.passed and V_DUP not in _rules(result)


def test_j_the_same_session_under_two_objectives_is_a_duplicate():
    shared = _res("res.shared", 200)
    a, b = _cs("a", [shared]), _cs("b", [shared])
    items = [_item_for(a, 1), _item_for(b, 1).model_copy(update={"item_id": "other", "day_slot": 2})]
    assert V_SESSION in _rules(_validate(items, {a.objective_id: a, b.objective_id: b}, BUDGET_20H))


def test_sessions_must_be_studied_in_order_and_without_skipping_ahead():
    cs = _cs("a", [_res("res.a", 200)])
    skipping = [_item_for(cs, 1, day=1), _item_for(cs, 3, day=2)]  # session 2 never scheduled
    assert V_SESSION in _rules(_validate(skipping, {cs.objective_id: cs}, BUDGET_20H))
    reversed_order = [_item_for(cs, 2, day=1), _item_for(cs, 1, day=3)]  # session 2 studied before session 1
    assert V_SESSION in _rules(_validate(reversed_order, {cs.objective_id: cs}, BUDGET_20H))
    # same-day items carry no order information: 1 then 2 on one day is fine
    assert _validate([_item_for(cs, 1, day=2), _item_for(cs, 2, day=2)], {cs.objective_id: cs}, BUDGET_20H).passed


def test_total_consumption_of_a_resource_cannot_exceed_its_duration():
    res = _res("res.a", 90)
    inflated = tuple(s.__class__(**{**s.__dict__, "est_minutes": 60}) for s in res.sessions)  # a corrupted candidate: 2 x 60 > 90
    bad = ResourceCandidateInfo(**{**res.__dict__, "sessions": inflated})
    cs = _cs("a", [bad])
    result = _validate([_item_for(cs, 1, day=1), _item_for(cs, 2, day=2)], {cs.objective_id: cs}, BUDGET_20H)
    assert V_SESSION in _rules(result)


def test_a_session_of_a_resource_not_offered_to_the_objective_is_still_a_referential_violation():
    cs = _cs("a", [_res("res.a", 200)])
    item = _item_for(cs, 1).model_copy(update={"resource_id": "res.ghost"})
    assert "V2_referential_integrity" in _rules(_validate([item], {cs.objective_id: cs}, BUDGET_20H))


# -- soft utilization rule ----------------------------------------------------------------------------------------------


def test_v_utilization_flags_an_underfilled_plan_only_when_in_order_material_would_still_fit():
    cs = _cs("a", [_res("res.a", 600)])
    sets = {cs.objective_id: cs}
    result = _validate([_item_for(cs, 1)], sets, BUDGET_20H)
    assert result.passed, "under-filling is soft: it never blocks a commit"
    assert V_UTILIZATION in {v.rule for v in result.soft_violations}
    filled = _plan(sets, BUDGET_20H)
    assert V_UTILIZATION not in {v.rule for v in _validate(filled, sets, BUDGET_20H).soft_violations}


# -- deterministic top-up used on the LLM path ---------------------------------------------------------------------------


def test_extend_plan_continues_existing_objectives_only_and_never_adds_a_skill_or_exceeds_the_ceiling():
    # plenty of supply (3 x 600 min for a, 600 for b): only the ceiling and the "existing objectives only" rule can stop the fill
    a = _cs("a", [_res("res.a", 600), _res("res.a2", 600), _res("res.a3", 600)], priority=2)
    b = _cs("b", [_res("res.b", 600)], priority=1)
    sets = {a.objective_id: a, b.objective_id: b}
    draft = [_item_for(a, 1)]  # the model chose only objective a, one session
    extra = extend_plan(draft, sets, hours_budget_minutes=BUDGET_20H)
    assert {i.skill_id for i in extra} == {"skill.a"}, "no new skill is introduced by the top-up"
    first_chain = [i.session.index for i in extra if i.resource_id == "res.a"]
    assert first_chain == list(range(2, len(first_chain) + 2)), "continues in order from the next session of the resource"
    assert 0.75 * BUDGET_20H <= _minutes(draft + extra) <= BUDGET_20H * 0.80, "fills to, and never past, the ceiling"
    assert _validate(draft + extra, sets, BUDGET_20H).passed
    assert extend_plan(draft + extra, sets, hours_budget_minutes=BUDGET_20H) == [], "already at the ceiling: nothing more is added"


def test_extend_plan_leaves_an_already_full_plan_alone():
    cs = _cs("a", [_res("res.a", 500)])
    full = [_item_for(cs, n, day=1 + n % 5) for n in range(1, 9)]
    assert extend_plan(full, {cs.objective_id: cs}, hours_budget_minutes=BUDGET_5H) == []


def test_summarize_utilization_reports_scheduled_and_available_minutes():
    cs = _cs("a", [_res("res.a", 500)])
    s = summarize_utilization([_item_for(cs, 1)], {cs.objective_id: cs}, hours_budget_minutes=BUDGET_20H)
    assert s.scheduled_minutes == _item_for(cs, 1).est_minutes and s.unscheduled_available_minutes > 0


def test_day_planner_spreads_load_and_keeps_chain_order():
    planner = DayPlanner(hours_budget_minutes=BUDGET_20H)
    days = [planner.place(45, not_before=1) for _ in range(20)]
    assert days == sorted(days) and set(days) <= {1, 2, 3, 4, 5} and len(set(days)) == 5
    assert DayPlanner(hours_budget_minutes=BUDGET_20H).place(45, not_before=4) == 4


def test_attach_reason_provenance_overwrites_model_supplied_ids_from_the_gap_report():
    cs = _cs("a", [_res("res.a", 90)])
    item = _item_for(cs, 1).model_copy(update={"reason": _item_for(cs, 1).reason.model_copy(update={"evidence_ids": ["ev-fake"], "graph_path": ["skill.fake"], "text": "phrase"})})
    gap = _gap("skill.a")
    gap.evidence_ids = ["ev-real"]
    out = attach_reason_provenance([item], gaps_by_skill={"skill.a": gap, "skill.p": _gap("skill.p")}, hard_prereqs_by_skill={"skill.a": ["skill.p", "skill.outside_scope"]})
    assert out[0].reason.evidence_ids == ["ev-real"]
    assert out[0].reason.graph_path == ["skill.p", "skill.a"], "only in-scope hard prerequisites, then the skill"
    assert out[0].reason.text == "phrase", "the LLM's wording is kept; only the IDs are code-owned"


# -- the LLM boundary: prompt + strict parser ---------------------------------------------------------------------------


def _draft(**item_fields) -> str:
    base = {"type": "resource", "objective_id": "obj.a", "skill_id": "skill.a", "resource_id": "res.long", "session_id": "res.long#1",
            "practice_item_ids": [], "est_minutes": 999, "difficulty": 1, "day_slot": 1, "depends_on": [], "reason_text": "go"}
    base.update(item_fields)
    return json.dumps({"items": [base], "overall_reason": "ok"})


def _sets() -> dict[str, ObjectiveCandidateSet]:
    return {"obj.a": _cs("a", [_res("res.long", 300), _res("res.short", 20)])}


def test_the_parser_resolves_a_real_session_and_takes_its_minutes_from_code_not_the_model():
    drafts, _ = parse_planner_response(_draft(session_id="res.long#2"), _sets())
    assert drafts[0].est_minutes == _sets()["obj.a"].resource("res.long").sessions[1].est_minutes != 999
    assert drafts[0].session["session_id"] == "res.long#2" and drafts[0].session["label"].endswith("Study Segment 2 of 7")


@pytest.mark.parametrize(
    "fields",
    [
        {"session_id": "res.long#99"},  # a session that does not exist
        {"session_id": "res.made.up#1", "resource_id": "res.made.up"},  # an invented resource
        {"session_id": "res.short#1"},  # a real session, but of a different resource than resource_id says
        {"session_id": None},  # a long resource with several sessions and none chosen
        {"session_id": "res.long#1", "objective_id": "obj.ghost"},
    ],
)
def test_the_parser_rejects_invented_or_ambiguous_sessions(fields):
    with pytest.raises(PlannerParseError):
        parse_planner_response(_draft(**fields), _sets())


def test_a_single_session_resource_needs_no_session_id_and_resolves_unambiguously():
    drafts, _ = parse_planner_response(_draft(resource_id="res.short", session_id=None, est_minutes=1), _sets())
    assert drafts[0].session["session_id"] == "res.short#1" and drafts[0].est_minutes == 20


def test_the_session_id_alone_fixes_the_resource():
    drafts, _ = parse_planner_response(_draft(resource_id=None, session_id="res.long#3"), _sets())
    assert drafts[0].resource_id == "res.long"


def test_the_prompt_describes_sessions_compactly_and_states_the_utilization_goal():
    prompt = build_planner_prompt(candidate_sets=_sets(), hours_budget_minutes=BUDGET_20H, mode="draft", new_skill_cap=3)
    payload = json.loads(prompt.split("Objectives with candidate sets (JSON):\n\n")[1].split("\n\nRespond with ONLY")[0])
    long = next(r for r in payload[0]["candidate_resources"] if r["resource_id"] == "res.long")
    assert long["sessions"] == 7 and long["total_min"] == 300 and "res.long#7" not in prompt, "ids are patterned, not spelled out"
    assert "aim for roughly 80%" in prompt and str(round(0.8 * BUDGET_20H)) in prompt
    assert len(prompt) < 6000, "compact enough for a small-token-per-minute provider"
