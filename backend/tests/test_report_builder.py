"""`app/tutor/report_builder.py::build_progress_report` — pure, hand-built
fixtures (same style as `tests/test_gap_engine.py`'s `tiny_graph_service`
cases): no DB, no LLM, just the Gap Engine's own already-computed statuses
bucketed deterministically.
"""
from __future__ import annotations

from app.gap.engine import BLOCKED, MET, MISSING, UNVERIFIED, WEAK, GapAnalysisResult, SkillGapEntry, Strength
from app.schemas.common import PlanItem
from app.tutor.report_builder import (
    MisconceptionStatusRecord,
    SkillStateRecord,
    StruggleSignalRecord,
    build_progress_report,
)


def _gap_result(**overrides) -> GapAnalysisResult:
    defaults = dict(
        role_id="role.ml_engineer",
        graph_version="v0.1.0-test",
        scope_skill_ids={"skill.a", "skill.b", "skill.c", "skill.d"},
        gaps=[
            SkillGapEntry(skill_id="skill.b", label="B", status=WEAK, gap_type="weak", required_level=2, current_level=1, evidence_ids=["ev_1"]),
            SkillGapEntry(skill_id="skill.c", label="C", status=MISSING, gap_type="missing", required_level=1, current_level=0),
            SkillGapEntry(skill_id="skill.d", label="D", status=BLOCKED, gap_type="missing", required_level=1, current_level=0, blocked_by=["skill.c"]),
        ],
        strengths=[Strength(skill_id="skill.a", label="A", required_level=1, current_level=1, tier_max="E2", mastery=0.9, evidence_ids=["ev_0"])],
        audit_flags=[],
        objectives=[],
        layers=[],
        prerequisite_edges=[],
    )
    defaults.update(overrides)
    return GapAnalysisResult(**defaults)


def test_acquired_comes_from_strengths():
    report = build_progress_report(
        learner_id="l1", period="all_time", gap_result=_gap_result(), skill_states={},
        struggle_signals=[], misconceptions=[], plan_items=[],
    )
    assert len(report.acquired) == 1
    assert report.acquired[0].skill_id == "skill.a"
    assert report.acquired[0].mastery == 0.9
    assert report.acquired[0].evidence_ids == ["ev_0"]


def test_weak_gaps_are_in_progress_with_band():
    skill_states = {"skill.b": SkillStateRecord(skill_id="skill.b", band="developing")}
    report = build_progress_report(
        learner_id="l1", period="all_time", gap_result=_gap_result(), skill_states=skill_states,
        struggle_signals=[], misconceptions=[], plan_items=[],
    )
    assert [s.skill_id for s in report.in_progress] == ["skill.b"]
    assert report.in_progress[0].band == "developing"
    assert report.in_progress[0].status == WEAK


def test_missing_and_blocked_are_remaining_gaps_not_in_progress():
    report = build_progress_report(
        learner_id="l1", period="all_time", gap_result=_gap_result(), skill_states={},
        struggle_signals=[], misconceptions=[], plan_items=[],
    )
    remaining_ids = {g.skill_id for g in report.remaining_gaps}
    assert remaining_ids == {"skill.c", "skill.d"}
    assert {s.skill_id for s in report.in_progress}.isdisjoint(remaining_ids)


def test_unverified_gap_is_a_remaining_gap():
    gap_result = _gap_result(
        gaps=[SkillGapEntry(skill_id="skill.e", label="E", status=UNVERIFIED, gap_type="unverified", required_level=1, current_level=0)],
    )
    report = build_progress_report(
        learner_id="l1", period="all_time", gap_result=gap_result, skill_states={},
        struggle_signals=[], misconceptions=[], plan_items=[],
    )
    assert [g.skill_id for g in report.remaining_gaps] == ["skill.e"]


def test_struggle_areas_include_open_signals_and_active_misconceptions_only():
    signals = [
        StruggleSignalRecord(signal_id="sig_1", skill_id="skill.b", signal_class="low_score", confidence="medium", status="open"),
        StruggleSignalRecord(signal_id="sig_2", skill_id="skill.b", signal_class="low_score", confidence="low", status="closed"),
    ]
    misconceptions = [
        MisconceptionStatusRecord(misconception_id="misc.x", skill_id="skill.c", status="confirmed"),
        MisconceptionStatusRecord(misconception_id="misc.y", skill_id="skill.c", status="resolved"),
    ]
    report = build_progress_report(
        learner_id="l1", period="all_time", gap_result=_gap_result(), skill_states={},
        struggle_signals=signals, misconceptions=misconceptions, plan_items=[],
    )
    assert len(report.struggle_areas) == 2
    signal_ids = {sa.signal_id for sa in report.struggle_areas if sa.signal_id}
    misconception_ids = {sa.misconception_id for sa in report.struggle_areas if sa.misconception_id}
    assert signal_ids == {"sig_1"}
    assert misconception_ids == {"misc.x"}


def test_completed_and_next_steps_partition_plan_items_by_status_and_order():
    items = [
        PlanItem(item_id="i1", type="resource", objective_id="obj.1", skill_id="skill.b", est_minutes=10, difficulty=1, day_slot=3, status="planned"),
        PlanItem(item_id="i2", type="resource", objective_id="obj.1", skill_id="skill.b", est_minutes=10, difficulty=1, day_slot=1, status="planned"),
        PlanItem(item_id="i3", type="practice", objective_id="obj.1", skill_id="skill.a", est_minutes=5, difficulty=1, day_slot=0, status="done"),
    ]
    report = build_progress_report(
        learner_id="l1", period="all_time", gap_result=_gap_result(), skill_states={},
        struggle_signals=[], misconceptions=[], plan_items=items,
    )
    assert [a.item_id for a in report.completed_work] == ["i3"]
    assert [a.item_id for a in report.next_steps] == ["i2", "i1"]  # sorted by day_slot


def test_deterministic_repeat_calls_produce_identical_report():
    kwargs = dict(
        learner_id="l1", period="all_time", gap_result=_gap_result(), skill_states={},
        struggle_signals=[], misconceptions=[], plan_items=[],
    )
    assert build_progress_report(**kwargs) == build_progress_report(**kwargs)
