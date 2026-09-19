"""Struggle Classifier tests (`app/assessment/struggle.py`) -- every one of
the six classes the Phase 8 brief names: low score, repeated misconception,
missing prerequisite, excessive difficulty, overload, insufficient
practice. Pure function over hand-built fixtures -- no DB, same shape as
`tests/test_gap_engine.py`/`tests/test_ranker.py`/`tests/test_plan_validator.py`.
"""
from __future__ import annotations

from app.gap.engine import MET, MISSING, UNVERIFIED, WEAK
from app.assessment.struggle import (
    COGNITIVE_OVERLOAD,
    EXCESSIVE_DIFFICULTY,
    INSUFFICIENT_PRACTICE,
    LOW_SCORE,
    MISSING_PREREQUISITE,
    REPEATED_MISCONCEPTION,
    ItemOutcome,
    StruggleContext,
    classify_struggle,
    primary_signal,
)


def _item(item_id, *, skill_id="skill.a", difficulty="medium", correct, misconception_id=None, time_sec=None):
    return ItemOutcome(item_id=item_id, skill_id=skill_id, difficulty=difficulty, correct=correct, misconception_id=misconception_id, time_sec=time_sec)


def _signals_of(signals, cls):
    return [s for s in signals if s.signal_class == cls]


# -- low score --------------------------------------------------------------


def test_low_score_fires_below_threshold_with_enough_items():
    items = [_item(f"i{i}", correct=False) for i in range(2)] + [_item("i2", correct=True)]
    ctx = StruggleContext(skill_id="skill.a")
    signals = _signals_of(classify_struggle(items, ctx), LOW_SCORE)
    assert len(signals) == 1
    assert signals[0].counts["score"] == 1 / 3


def test_low_score_does_not_fire_with_too_few_items():
    items = [_item("i0", correct=False), _item("i1", correct=False)]  # only 2 items, min is 3
    ctx = StruggleContext(skill_id="skill.a")
    assert _signals_of(classify_struggle(items, ctx), LOW_SCORE) == []


def test_low_score_does_not_fire_above_threshold():
    items = [_item(f"i{i}", correct=True) for i in range(3)]
    ctx = StruggleContext(skill_id="skill.a")
    assert _signals_of(classify_struggle(items, ctx), LOW_SCORE) == []


def test_low_score_confidence_steps_up_when_severe():
    items = [_item(f"i{i}", correct=False) for i in range(3)]  # score 0.0 < 0.4 severe threshold
    ctx = StruggleContext(skill_id="skill.a")
    signals = _signals_of(classify_struggle(items, ctx), LOW_SCORE)
    assert signals[0].confidence == "medium"


def test_low_score_is_not_a_reflection_trigger_by_itself():
    """design §19.2: 'Not by itself a reflection trigger' -- a score right
    at the threshold doesn't fire at all (score >= threshold never fires),
    and `primary_signal` separately excludes low-confidence signals from
    routing (see the precedence tests below)."""
    items = [_item(f"i{i}", correct=(i < 3)) for i in range(5)]  # 3/5 = 0.6, not below the 0.6 threshold
    ctx = StruggleContext(skill_id="skill.a")
    assert _signals_of(classify_struggle(items, ctx), LOW_SCORE) == []


# -- repeated misconception --------------------------------------------------------------


def test_single_occurrence_is_suspected_with_low_confidence():
    items = [_item("i0", correct=False, misconception_id="misc.x")]
    ctx = StruggleContext(skill_id="skill.a")
    signals = _signals_of(classify_struggle(items, ctx), REPEATED_MISCONCEPTION)
    assert len(signals) == 1
    assert signals[0].confidence == "low"
    assert signals[0].counts["status"] == "suspected"


def test_two_occurrences_in_one_attempt_is_confirmed_with_high_confidence():
    items = [_item("i0", correct=False, misconception_id="misc.x"), _item("i1", correct=False, misconception_id="misc.x")]
    ctx = StruggleContext(skill_id="skill.a")
    signals = _signals_of(classify_struggle(items, ctx), REPEATED_MISCONCEPTION)
    assert len(signals) == 1
    assert signals[0].confidence == "high"
    assert signals[0].counts["status"] == "confirmed"
    assert sorted(signals[0].evidence_ids) == ["i0", "i1"]


def test_confirmed_across_separate_attempts_via_prior_occurrence_count():
    items = [_item("i1", correct=False, misconception_id="misc.x")]  # 1 item this attempt
    ctx = StruggleContext(skill_id="skill.a", prior_misconception_item_counts={"misc.x": 1})  # 1 prior item
    signals = _signals_of(classify_struggle(items, ctx), REPEATED_MISCONCEPTION)
    assert signals[0].confidence == "high"
    assert signals[0].counts["status"] == "confirmed"
    assert signals[0].counts["total_occurrences"] == 2


def test_different_misconceptions_are_reported_as_separate_signals():
    items = [_item("i0", correct=False, misconception_id="misc.x"), _item("i1", correct=False, misconception_id="misc.y")]
    ctx = StruggleContext(skill_id="skill.a")
    signals = _signals_of(classify_struggle(items, ctx), REPEATED_MISCONCEPTION)
    assert {s.counts["misconception_id"] for s in signals} == {"misc.x", "misc.y"}


def test_correct_items_never_carry_a_misconception_tag_and_do_not_fire():
    items = [_item("i0", correct=True, misconception_id=None)]
    ctx = StruggleContext(skill_id="skill.a")
    assert _signals_of(classify_struggle(items, ctx), REPEATED_MISCONCEPTION) == []


# -- missing prerequisite --------------------------------------------------------------


def test_direct_prereq_block_items_failing_confirms_missing_prerequisite_with_high_confidence():
    items = [
        _item("i0", skill_id="skill.b", correct=True),
        _item("i1", skill_id="skill.prereq", correct=False),
        _item("i2", skill_id="skill.prereq", correct=False),
    ]
    ctx = StruggleContext(skill_id="skill.b", hard_prerequisite_status={"skill.prereq": MISSING})
    signals = _signals_of(classify_struggle(items, ctx), MISSING_PREREQUISITE)
    assert len(signals) == 1
    assert signals[0].confidence == "high"
    assert signals[0].counts["confirmed_by"] == "probe"


def test_direct_probe_score_below_threshold_confirms_missing_prerequisite():
    items = [_item("i0", skill_id="skill.b", correct=False)]
    ctx = StruggleContext(
        skill_id="skill.b", hard_prerequisite_status={"skill.prereq": WEAK}, prerequisite_probe_scores={"skill.prereq": 0.3}
    )
    signals = _signals_of(classify_struggle(items, ctx), MISSING_PREREQUISITE)
    assert len(signals) == 1
    assert signals[0].confidence == "high"


def test_attribution_only_via_misconception_root_skill_is_medium_confidence():
    items = [_item("i0", skill_id="skill.b", correct=False, misconception_id="misc.rooted")]
    ctx = StruggleContext(
        skill_id="skill.b",
        hard_prerequisite_status={"skill.prereq": WEAK},
        misconception_root_skill={"misc.rooted": "skill.prereq"},
    )
    signals = _signals_of(classify_struggle(items, ctx), MISSING_PREREQUISITE)
    assert len(signals) == 1
    assert signals[0].confidence == "medium"
    assert signals[0].counts["confirmed_by"] == "attribution"


def test_missing_prerequisite_does_not_fire_when_all_prerequisites_are_met():
    items = [_item("i0", skill_id="skill.b", correct=False)]
    ctx = StruggleContext(skill_id="skill.b", hard_prerequisite_status={"skill.prereq": MET})
    assert _signals_of(classify_struggle(items, ctx), MISSING_PREREQUISITE) == []


def test_unverified_prerequisite_alone_does_not_confirm_without_a_probe_or_attribution():
    # UNVERIFIED prereq -- still "not MET" so it's a candidate, but with neither a
    # failing probe nor attribution, nothing should fire.
    items = [_item("i0", skill_id="skill.b", correct=True)]
    ctx = StruggleContext(skill_id="skill.b", hard_prerequisite_status={"skill.prereq": UNVERIFIED})
    assert _signals_of(classify_struggle(items, ctx), MISSING_PREREQUISITE) == []


# -- excessive difficulty --------------------------------------------------------------


def test_excessive_difficulty_fires_on_above_level_failures_with_prereqs_met():
    items = [_item("i0", difficulty="hard", correct=False), _item("i1", difficulty="hard", correct=False)]
    ctx = StruggleContext(skill_id="skill.a", current_level=1, hard_prerequisite_status={"skill.p": MET})
    signals = _signals_of(classify_struggle(items, ctx), EXCESSIVE_DIFFICULTY)
    assert len(signals) == 1
    assert signals[0].confidence == "medium"


def test_excessive_difficulty_does_not_fire_when_a_prerequisite_is_not_met():
    items = [_item("i0", difficulty="hard", correct=False), _item("i1", difficulty="hard", correct=False)]
    ctx = StruggleContext(skill_id="skill.a", current_level=1, hard_prerequisite_status={"skill.p": WEAK})
    assert _signals_of(classify_struggle(items, ctx), EXCESSIVE_DIFFICULTY) == []


def test_excessive_difficulty_does_not_fire_when_a_repeated_misconception_also_fired():
    items = [
        _item("i0", difficulty="hard", correct=False, misconception_id="misc.x"),
        _item("i1", difficulty="hard", correct=False, misconception_id="misc.x"),
    ]
    ctx = StruggleContext(skill_id="skill.a", current_level=1, hard_prerequisite_status={"skill.p": MET})
    signals = classify_struggle(items, ctx)
    assert _signals_of(signals, REPEATED_MISCONCEPTION)  # sanity: it did fire
    assert _signals_of(signals, EXCESSIVE_DIFFICULTY) == []  # excluded in favor of the more specific class


def test_excessive_difficulty_does_not_fire_on_items_at_or_below_level():
    items = [_item("i0", difficulty="easy", correct=False), _item("i1", difficulty="medium", correct=False)]
    ctx = StruggleContext(skill_id="skill.a", current_level=2)  # medium == level 2, easy < level 2
    assert _signals_of(classify_struggle(items, ctx), EXCESSIVE_DIFFICULTY) == []


def test_excessive_difficulty_requires_min_items():
    items = [_item("i0", difficulty="hard", correct=False)]  # only 1 above-level item, min is 2
    ctx = StruggleContext(skill_id="skill.a", current_level=1, hard_prerequisite_status={"skill.p": MET})
    assert _signals_of(classify_struggle(items, ctx), EXCESSIVE_DIFFICULTY) == []


# -- cognitive overload --------------------------------------------------------------


def test_overload_requires_at_least_two_corroborating_signals():
    items = [_item("i0", correct=True)]
    ctx = StruggleContext(skill_id="skill.a", planned_vs_actual_ratio=2.0)  # only one signal
    assert _signals_of(classify_struggle(items, ctx), COGNITIVE_OVERLOAD) == []


def test_overload_fires_with_two_corroborating_signals_medium_confidence():
    items = [_item("i0", correct=True)]
    ctx = StruggleContext(skill_id="skill.a", planned_vs_actual_ratio=2.0, completion_rate=0.4)
    signals = _signals_of(classify_struggle(items, ctx), COGNITIVE_OVERLOAD)
    assert len(signals) == 1
    assert signals[0].confidence == "medium"
    assert set(signals[0].counts["corroborating_signals"]) == {"planned_vs_actual", "low_completion"}


def test_overload_confidence_is_high_with_self_report():
    items = [_item("i0", correct=True)]
    ctx = StruggleContext(skill_id="skill.a", planned_vs_actual_ratio=2.0, self_reported_overload=True)
    signals = _signals_of(classify_struggle(items, ctx), COGNITIVE_OVERLOAD)
    assert signals[0].confidence == "high"


def test_time_alone_never_triggers_overload():
    """Phase 8 brief: 'time and retries are corroborating evidence, not sole
    authority' -- an item's raw time_sec must never gate overload by
    itself; only the independently-supplied corroborating context signals do."""
    items = [_item("i0", correct=True, time_sec=99999)]  # an absurdly long time, ignored
    ctx = StruggleContext(skill_id="skill.a")
    assert _signals_of(classify_struggle(items, ctx), COGNITIVE_OVERLOAD) == []


def test_retries_alone_never_triggers_overload():
    items = [_item("i0", correct=True)]
    ctx = StruggleContext(skill_id="skill.a", retries_trend_rising=True)  # only one corroborating signal
    assert _signals_of(classify_struggle(items, ctx), COGNITIVE_OVERLOAD) == []


def test_too_many_new_skills_counts_as_a_corroborating_signal():
    items = [_item("i0", correct=True)]
    ctx = StruggleContext(skill_id="skill.a", new_skills_active=5, new_skill_concurrency_cap=3, retries_trend_rising=True)
    signals = _signals_of(classify_struggle(items, ctx), COGNITIVE_OVERLOAD)
    assert len(signals) == 1
    assert "too_many_new_skills" in signals[0].counts["corroborating_signals"]


# -- insufficient practice --------------------------------------------------------------


def test_insufficient_practice_fires_on_low_mastery_and_few_observations():
    items = [_item("i0", correct=False)]
    ctx = StruggleContext(skill_id="skill.a", mastery_estimate=0.3, n_obs=2, resource_recently_completed=True)
    signals = _signals_of(classify_struggle(items, ctx), INSUFFICIENT_PRACTICE)
    assert len(signals) == 1
    assert signals[0].confidence == "medium"


def test_insufficient_practice_does_not_fire_with_enough_observations():
    items = [_item("i0", correct=False)]
    ctx = StruggleContext(skill_id="skill.a", mastery_estimate=0.3, n_obs=4)  # n_obs >= 4
    assert _signals_of(classify_struggle(items, ctx), INSUFFICIENT_PRACTICE) == []


def test_insufficient_practice_does_not_fire_when_mastery_already_developing_or_above():
    items = [_item("i0", correct=True)]
    ctx = StruggleContext(skill_id="skill.a", mastery_estimate=0.6, n_obs=1)
    assert _signals_of(classify_struggle(items, ctx), INSUFFICIENT_PRACTICE) == []


def test_insufficient_practice_does_not_fire_when_errors_are_concentrated_on_one_tag():
    """design: 'errors not concentrated on one tag' -- a repeated
    misconception is a different, more specific class."""
    items = [
        _item("i0", correct=False, misconception_id="misc.x"),
        _item("i1", correct=False, misconception_id="misc.x"),
    ]
    ctx = StruggleContext(skill_id="skill.a", mastery_estimate=0.3, n_obs=1)
    signals = classify_struggle(items, ctx)
    assert _signals_of(signals, REPEATED_MISCONCEPTION)  # sanity
    assert _signals_of(signals, INSUFFICIENT_PRACTICE) == []


def test_insufficient_practice_requires_a_recently_completed_resource():
    items = [_item("i0", correct=False)]
    ctx = StruggleContext(skill_id="skill.a", mastery_estimate=0.3, n_obs=1, resource_recently_completed=False)
    assert _signals_of(classify_struggle(items, ctx), INSUFFICIENT_PRACTICE) == []


# -- multiple classes can fire; precedence for a single primary action --------------------------------------------------------------


def test_multiple_classes_can_fire_simultaneously():
    items = [
        _item("i0", correct=False, misconception_id="misc.x"),
        _item("i1", correct=False, misconception_id="misc.x"),
        _item("i2", correct=False),
    ]
    ctx = StruggleContext(skill_id="skill.a")
    signals = classify_struggle(items, ctx)
    classes = {s.signal_class for s in signals}
    assert REPEATED_MISCONCEPTION in classes
    assert LOW_SCORE in classes  # 3 items, 0/3 correct


def test_primary_signal_prefers_misconception_over_low_score():
    items = [
        _item("i0", correct=False, misconception_id="misc.x"),
        _item("i1", correct=False, misconception_id="misc.x"),
        _item("i2", correct=False),
    ]
    ctx = StruggleContext(skill_id="skill.a")
    signals = classify_struggle(items, ctx)
    primary = primary_signal(signals)
    assert primary is not None
    assert primary.signal_class == REPEATED_MISCONCEPTION


def test_primary_signal_ignores_low_or_suspected_confidence_signals():
    """design §19.3: 'Low or suspected -> schedule_probe', not a routing trigger."""
    items = [_item("i0", correct=False, misconception_id="misc.x")]  # only 1 occurrence -> suspected/low
    ctx = StruggleContext(skill_id="skill.a")
    signals = classify_struggle(items, ctx)
    assert primary_signal(signals) is None


def test_no_signals_is_a_valid_result():
    items = [_item("i0", correct=True), _item("i1", correct=True), _item("i2", correct=True)]
    # a healthy mastery_estimate/n_obs so insufficient_practice doesn't fire on the
    # StruggleContext's own "nothing known yet" defaults -- in production these
    # reflect the just-computed post-update mastery, not an untouched default.
    ctx = StruggleContext(skill_id="skill.a", mastery_estimate=0.8, n_obs=4)
    assert classify_struggle(items, ctx) == []
    assert primary_signal([]) is None
