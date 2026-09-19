"""Mastery Updater tests (`app/assessment/mastery.py`). Pure function over
hand-built `LearnerSkillRecord` fixtures -- no DB. Confirms design §10.4's
Beta-count update formula and, per the Phase 8 brief's explicit
instruction, that mastery is always surfaced as an **estimate** (band +
confidence), never bare ground truth.
"""
from __future__ import annotations

from app.assessment.mastery import compute_band, compute_confidence, mastery_estimate, update_mastery
from app.gap.engine import LearnerSkillRecord


def test_correct_easy_item_increases_alpha_by_the_easy_weight():
    outcome = update_mastery(None, skill_id="skill.a", correct=True, difficulty="easy")
    assert outcome.alpha == 1.0 + 0.7
    assert outcome.beta == 1.0  # uninformative Beta(1,1) prior, untouched
    assert outcome.n_obs == 1


def test_incorrect_hard_item_increases_beta_by_the_reversed_hard_weight():
    # "the reverse for incorrect": hard-correct=1.3, but hard-incorrect uses the easy weight (0.7) --
    # missing a hard item is *less* surprising than missing an easy one.
    outcome = update_mastery(None, skill_id="skill.a", correct=False, difficulty="hard")
    assert outcome.beta == 1.0 + 0.7
    assert outcome.alpha == 1.0


def test_incorrect_easy_item_is_more_informative_of_weakness():
    outcome = update_mastery(None, skill_id="skill.a", correct=False, difficulty="easy")
    assert outcome.beta == 1.0 + 1.3  # reversed: easy-incorrect uses the hard weight


def test_accumulates_on_top_of_existing_state_not_a_reseed():
    existing = LearnerSkillRecord(skill_id="skill.a", alpha=5.0, beta=2.0, tier_max="E2", n_obs=2)
    outcome = update_mastery(existing, skill_id="skill.a", correct=True, difficulty="medium")
    assert outcome.alpha == 5.0 + 1.0  # accumulated, not reseeded to a flat E3 prior
    assert outcome.beta == 2.0
    assert outcome.n_obs == 3
    assert outcome.tier_max == "E3"  # assessed evidence is always the strongest tier


def test_tier_max_becomes_e3_even_from_a_lower_starting_tier():
    existing = LearnerSkillRecord(skill_id="skill.a", alpha=0.5, beta=1.0, tier_max="E0", n_obs=0)
    outcome = update_mastery(existing, skill_id="skill.a", correct=True, difficulty="medium")
    assert outcome.tier_max == "E3"


# -- mastery is always an estimate, never asserted as fact --------------------------------------


def test_mastery_estimate_is_a_plain_ratio():
    assert mastery_estimate(3.0, 1.0) == 0.75
    assert mastery_estimate(0.0, 0.0) == 0.0  # no division by zero


def test_outcome_always_carries_band_and_confidence_alongside_the_raw_numbers():
    outcome = update_mastery(None, skill_id="skill.a", correct=True, difficulty="medium")
    assert outcome.band in {"unknown", "learning", "developing", "proficient"}
    assert outcome.confidence in {"low", "medium", "high"}


# -- band table (design §10.4) --------------------------------------------------------------


def test_band_unknown_when_no_observations_and_low_tier():
    assert compute_band(0.9, n_obs=0, tier_max="E0") == "unknown"
    assert compute_band(0.9, n_obs=0, tier_max="E1") == "unknown"


def test_band_learning_below_0_55():
    assert compute_band(0.3, n_obs=2, tier_max="E3") == "learning"


def test_band_developing_between_0_55_and_0_75():
    assert compute_band(0.6, n_obs=2, tier_max="E3") == "developing"


def test_band_proficient_requires_both_high_mastery_and_enough_observations():
    assert compute_band(0.8, n_obs=3, tier_max="E3") == "proficient"


def test_band_falls_back_to_developing_when_mastery_high_but_n_obs_too_low():
    assert compute_band(0.9, n_obs=1, tier_max="E3") == "developing"


# -- confidence buckets --------------------------------------------------------------


def test_confidence_low_at_0_or_1_observations():
    assert compute_confidence(0) == "low"
    assert compute_confidence(1) == "low"


def test_confidence_medium_at_2_or_3_observations():
    assert compute_confidence(2) == "medium"
    assert compute_confidence(3) == "medium"


def test_confidence_high_at_4_or_more_observations():
    assert compute_confidence(4) == "high"
    assert compute_confidence(10) == "high"
