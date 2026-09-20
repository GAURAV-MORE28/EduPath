"""Resource sessionization (`app/planning/sessions.py`, Stage 2): the deterministic rules that turn one real resource into
study sessions. Pure functions -- no DB, no gateway, no LLM -- so the invariants are property-tested over many durations/caps
rather than sampled: the segmentation must never exceed the cap, never produce an absurdly small segment, always account for
the resource's full duration, and never invent metadata (test matrix A, B, K)."""
from __future__ import annotations

import pytest

from app.planning.sessions import (
    SessionizationPolicy,
    make_session_id,
    segment_durations,
    session_meta,
    sessionize_resource,
)


def _sessions(duration: int, *, cap: int = 45, title: str = "FastAPI Course", **kw):
    return sessionize_resource(
        resource_id="res.fastapi", title=title, duration_min=duration, policy=SessionizationPolicy(max_session_minutes=cap), **kw
    )


# -- A. short resource ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize("duration", [1, 10, 15, 30, 45])
def test_a_resource_that_fits_one_session_is_a_single_complete_session_never_split(duration):
    sessions = _sessions(duration)
    assert len(sessions) == 1
    only = sessions[0]
    assert only.is_complete_resource and (only.index, only.count) == (1, 1)
    assert only.est_minutes == only.resource_duration_min == duration
    assert only.label == "FastAPI Course"  # a whole resource is not renamed "Study Segment"
    assert (only.start_min, only.end_min) == (0, duration)


# -- B. long resource ------------------------------------------------------------------------------------------------


def test_a_long_resource_is_divided_into_capped_near_equal_segments_that_cover_it_exactly():
    sessions = _sessions(600)
    minutes = [s.est_minutes for s in sessions]
    assert len(sessions) == 14  # ceil(600 / 45)
    assert sum(minutes) == 600
    assert max(minutes) <= 45 and min(minutes) >= 42 and max(minutes) - min(minutes) <= 1
    assert [s.index for s in sessions] == list(range(1, 15)) and {s.count for s in sessions} == {14}


def test_session_ids_labels_and_nominal_offsets_are_derived_only_from_the_resource_row():
    sessions = _sessions(100, title="Algebra Basics")
    assert [s.session_id for s in sessions] == ["res.fastapi#1", "res.fastapi#2", "res.fastapi#3"]
    assert [s.label for s in sessions] == [f"Algebra Basics — Study Segment {i} of 3" for i in (1, 2, 3)]
    # nominal, contiguous minute ranges over the resource's own estimated duration -- not chapter boundaries
    assert [(s.start_min, s.end_min) for s in sessions] == [(0, 34), (34, 67), (67, 100)]
    assert all(s.resource_duration_min == 100 for s in sessions)


def test_sessions_preserve_the_resource_metadata_and_never_add_any():
    sessions = _sessions(
        120,
        provider="Khan Academy",
        url="https://example.org/course",
        modality="watch",
        resource_type="course",
        difficulty=2,
        skill_id="skill.fastapi",
        curation_tier="curated",
    )
    for s in sessions:
        assert (s.resource_id, s.title, s.provider, s.url) == ("res.fastapi", "FastAPI Course", "Khan Academy", "https://example.org/course")
        assert (s.modality, s.resource_type, s.difficulty, s.skill_id, s.curation_tier) == ("watch", "course", 2, "skill.fastapi", "curated")
        assert s.provenance == "catalog"
        # the stored plan-item provenance is exactly the derived facts, nothing else
        assert set(session_meta(s).__dict__) == {
            "session_id", "resource_id", "index", "count", "label", "start_min", "end_min", "resource_duration_min",
        }


# -- K. duration boundary --------------------------------------------------------------------------------------------


def test_the_cap_is_the_exact_boundary_between_one_session_and_two():
    assert segment_durations(45, SessionizationPolicy(45)) == [45]
    assert segment_durations(46, SessionizationPolicy(45)) == [23, 23]
    assert segment_durations(90, SessionizationPolicy(45)) == [45, 45]
    assert segment_durations(91, SessionizationPolicy(45)) == [31, 30, 30]
    assert segment_durations(0, SessionizationPolicy(45)) == [] and segment_durations(-5, SessionizationPolicy(45)) == []
    assert _sessions(0) == ()


def test_segmentation_invariants_hold_for_every_duration_and_cap():
    """Property test over the whole plausible domain (not a sample): full coverage, hard cap, no tiny fragments, near-equal sizes,
    determinism."""
    for cap in range(5, 61):
        policy = SessionizationPolicy(max_session_minutes=cap)
        for duration in range(1, 1001):
            parts = segment_durations(duration, policy)
            assert sum(parts) == duration, (duration, cap)
            assert max(parts) <= cap, (duration, cap)
            assert max(parts) - min(parts) <= 1, (duration, cap)
            if len(parts) > 1:
                assert min(parts) >= policy.effective_min_minutes, (duration, cap, parts)
            assert parts == segment_durations(duration, policy)


def test_minimum_session_length_is_configurable_and_clamped_to_half_the_cap():
    assert SessionizationPolicy(max_session_minutes=45, min_session_minutes=20).effective_min_minutes == 20
    assert SessionizationPolicy(max_session_minutes=30, min_session_minutes=20).effective_min_minutes == 15  # small cap stays feasible
    assert SessionizationPolicy(max_session_minutes=45, min_session_minutes=5).effective_min_minutes == 5


def test_the_learner_cap_becomes_the_maximum_session_length_bounded_by_the_v6_sitting_limit():
    assert SessionizationPolicy.for_learner(30).max_session_minutes == 30
    assert SessionizationPolicy.for_learner(0).max_session_minutes == 45  # unset -> default
    assert SessionizationPolicy.for_learner(240).max_session_minutes == 60  # never longer than one V6 sitting


def test_make_session_id_is_the_only_id_format():
    assert make_session_id("res.a", 3) == "res.a#3"
