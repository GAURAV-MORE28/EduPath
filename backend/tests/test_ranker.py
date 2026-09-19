"""Resource Retriever/Ranker tests (`app/retrieval/ranker.py`): the
eligibility filter, hybrid dense+keyword relevance/RRF, the design §15.3
ranking formula's components, MMR duplicate removal, and the full
`recommend()` pipeline. Pure functions over hand-built `ResourceCandidate`
fixtures -- no DB, no gateway, no LLM (same "unit-testable with hand-built
fixtures" shape as `tests/test_gap_engine.py`).
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.retrieval.ranker import (
    ResourceCandidate,
    ResourceUsageRecord,
    eligibility_checks,
    filter_eligible,
    mmr_diversify,
    recommend,
    score_candidates,
)

TODAY = date(2026, 1, 1)


def _candidate(
    resource_id: str,
    *,
    title: str = "Title",
    provider: str = "khanacademy",
    type_: str = "article",
    duration_min: int = 20,
    modality: str = "read",
    prerequisite_skill_ids: list[str] | None = None,
    learning_objective_text: str = "",
    language: str = "en",
    curation_tier: str = "curated",
    last_verified_at: date | None = TODAY,
    link_status: str = "ok",
    embedding: list[float] | None = None,
    level_from: int = 1,
    level_to: int = 2,
) -> ResourceCandidate:
    return ResourceCandidate(
        resource_id=resource_id,
        title=title,
        url=f"https://example.org/{resource_id}",
        provider=provider,
        type=type_,
        duration_min=duration_min,
        modality=modality,
        prerequisite_skill_ids=prerequisite_skill_ids or [],
        learning_objective_text=learning_objective_text,
        language=language,
        curation_tier=curation_tier,
        last_verified_at=last_verified_at,
        link_status=link_status,
        embedding=embedding,
        level_from=level_from,
        level_to=level_to,
    )


# -- eligibility filter (design §14.3 point 2) --------------------------------


def test_broken_link_is_ineligible():
    c = _candidate("res.a", link_status="broken")
    checks = eligibility_checks(c, current_level=1, met_skill_ids=set(), session_cap_minutes=45, language="", excluded_modalities=set())
    assert checks["link_ok"] is False
    assert filter_eligible([c], current_level=1, met_skill_ids=set(), session_cap_minutes=45, language="", excluded_modalities=set()) == []


def test_only_ok_link_status_is_eligible_redirected_and_broken_are_not():
    ok = _candidate("res.ok", link_status="ok")
    redirected = _candidate("res.redirected", link_status="redirected")
    broken = _candidate("res.broken", link_status="broken")
    eligible = filter_eligible(
        [ok, redirected, broken], current_level=1, met_skill_ids=set(), session_cap_minutes=45, language="", excluded_modalities=set()
    )
    # design §14.3 point 2's eligibility filter is literally "link_status = ok" -- "redirected"
    # is a distinct value (design §15.1: ok/redirected/broken), not folded into "ok" here.
    assert {c.resource_id for c in eligible} == {"res.ok"}


def test_difficulty_band_must_overlap_current_and_next_level():
    at_level = _candidate("res.at", level_from=2, level_to=2)
    one_above = _candidate("res.above", level_from=3, level_to=3)
    too_far_above = _candidate("res.far", level_from=4, level_to=4)
    below = _candidate("res.below", level_from=1, level_to=1)
    eligible = filter_eligible(
        [at_level, one_above, too_far_above, below],
        current_level=2,
        met_skill_ids=set(),
        session_cap_minutes=45,
        language="",
        excluded_modalities=set(),
    )
    ids = {c.resource_id for c in eligible}
    assert "res.at" in ids
    assert "res.above" in ids  # current_level + 1 overlaps
    assert "res.far" not in ids
    assert "res.below" not in ids


def test_unmet_prerequisite_is_ineligible():
    c = _candidate("res.a", prerequisite_skill_ids=["skill.x", "skill.y"])
    ineligible = filter_eligible([c], current_level=1, met_skill_ids={"skill.x"}, session_cap_minutes=45, language="", excluded_modalities=set())
    assert ineligible == []
    eligible = filter_eligible([c], current_level=1, met_skill_ids={"skill.x", "skill.y"}, session_cap_minutes=45, language="", excluded_modalities=set())
    assert len(eligible) == 1


def test_duration_over_session_cap_is_ineligible():
    short = _candidate("res.short", duration_min=20)
    long = _candidate("res.long", duration_min=90)
    eligible = filter_eligible([short, long], current_level=1, met_skill_ids=set(), session_cap_minutes=45, language="", excluded_modalities=set())
    assert {c.resource_id for c in eligible} == {"res.short"}


def test_language_mismatch_is_ineligible():
    en = _candidate("res.en", language="en")
    fr = _candidate("res.fr", language="fr")
    eligible = filter_eligible([en, fr], current_level=1, met_skill_ids=set(), session_cap_minutes=45, language="en", excluded_modalities=set())
    assert {c.resource_id for c in eligible} == {"res.en"}


def test_excluded_modality_is_ineligible():
    watch = _candidate("res.watch", modality="watch")
    read = _candidate("res.read", modality="read")
    eligible = filter_eligible(
        [watch, read], current_level=1, met_skill_ids=set(), session_cap_minutes=45, language="", excluded_modalities={"watch"}
    )
    assert {c.resource_id for c in eligible} == {"res.read"}


# -- hybrid retrieval relevance / RRF (design §14.3 point 3, §15.3) -----------


def test_relevance_favors_the_candidate_matching_query_text_and_embedding():
    close = _candidate(
        "res.close", title="Chain Rule Basics", learning_objective_text="derivatives chain rule composite functions",
        embedding=[1.0, 0.0, 0.0],
    )
    far = _candidate(
        "res.far", title="SQL Joins", learning_objective_text="databases relational joins queries", embedding=[0.0, 1.0, 0.0]
    )
    ranked = score_candidates(
        [close, far],
        query_embedding=[1.0, 0.0, 0.0],
        query_text="chain rule derivatives",
        current_level=1,
        modality_order=["do", "read", "watch"],
        session_cap_minutes=45,
        learner_history=[],
        skill_id="skill.chain_rule",
        as_of=TODAY,
    )
    assert ranked[0].candidate.resource_id == "res.close"
    assert ranked[0].score_breakdown["relevance"] > ranked[1].score_breakdown["relevance"]


def test_relevance_is_zero_to_one_normalized():
    a = _candidate("res.a", embedding=[1.0, 0.0])
    b = _candidate("res.b", embedding=[0.0, 1.0])
    ranked = score_candidates(
        [a, b],
        query_embedding=[1.0, 0.0],
        query_text="",
        current_level=1,
        modality_order=["do", "read", "watch"],
        session_cap_minutes=45,
        learner_history=[],
        skill_id="skill.x",
        as_of=TODAY,
    )
    for r in ranked:
        assert 0.0 <= r.score_breakdown["relevance"] <= 1.0
    assert ranked[0].score_breakdown["relevance"] == 1.0  # the top-ranked resource normalizes to exactly 1.0


# -- ranking formula components (design §15.3) --------------------------------


def test_level_fit_peaks_when_level_from_equals_current_level():
    ranked = score_candidates(
        [_candidate("res.a", level_from=2, level_to=2)],
        query_embedding=[],
        query_text="",
        current_level=2,
        modality_order=["do", "read", "watch"],
        session_cap_minutes=45,
        learner_history=[],
        skill_id="skill.x",
        as_of=TODAY,
    )
    assert ranked[0].score_breakdown["level_fit"] == 1.0


def test_quality_prefers_curated_and_recently_verified():
    curated_fresh = _candidate("res.a", curation_tier="curated", last_verified_at=TODAY)
    unvetted_stale = _candidate("res.b", curation_tier="unvetted", last_verified_at=TODAY - timedelta(days=1000))
    ranked = score_candidates(
        [curated_fresh, unvetted_stale],
        query_embedding=[],
        query_text="",
        current_level=1,
        modality_order=["do", "read", "watch"],
        session_cap_minutes=45,
        learner_history=[],
        skill_id="skill.x",
        as_of=TODAY,
    )
    by_id = {r.candidate.resource_id: r for r in ranked}
    assert by_id["res.a"].score_breakdown["quality"] > by_id["res.b"].score_breakdown["quality"]


def test_never_verified_gets_the_recency_floor():
    never = _candidate("res.a", curation_tier="curated", last_verified_at=None)
    ranked = score_candidates(
        [never],
        query_embedding=[],
        query_text="",
        current_level=1,
        modality_order=["do", "read", "watch"],
        session_cap_minutes=45,
        learner_history=[],
        skill_id="skill.x",
        as_of=TODAY,
    )
    assert ranked[0].score_breakdown["quality"] == pytest.approx(0.5)  # curated (1.0) * floor recency (0.5)


def test_modality_preference_ranks_the_preferred_modality_first():
    do = _candidate("res.do", modality="do", embedding=[1.0])
    watch = _candidate("res.watch", modality="watch", embedding=[1.0])
    ranked = score_candidates(
        [do, watch],
        query_embedding=[1.0],
        query_text="",
        current_level=1,
        modality_order=["do", "read", "watch"],
        session_cap_minutes=45,
        learner_history=[],
        skill_id="skill.x",
        as_of=TODAY,
    )
    # Otherwise-identical candidates -- the learner's first-choice modality must rank first.
    assert ranked[0].candidate.resource_id == "res.do"
    assert ranked[0].score_breakdown["modality_pref"] == 1.0
    watch_breakdown = next(r for r in ranked if r.candidate.resource_id == "res.watch").score_breakdown
    assert watch_breakdown["modality_pref"] < 1.0


def test_modality_not_in_preference_order_scores_zero():
    ranked = score_candidates(
        [_candidate("res.a", modality="do")],
        query_embedding=[],
        query_text="",
        current_level=1,
        modality_order=["read", "watch"],  # "do" isn't in the learner's ordered preferences at all
        session_cap_minutes=45,
        learner_history=[],
        skill_id="skill.x",
        as_of=TODAY,
    )
    assert ranked[0].score_breakdown["modality_pref"] == 0.0


def test_duration_fit_is_full_within_cap_and_decays_beyond_it():
    within = _candidate("res.within", duration_min=30)
    over = _candidate("res.over", duration_min=90)  # would already fail eligibility, but score_candidates itself is pure
    ranked = score_candidates(
        [within, over],
        query_embedding=[],
        query_text="",
        current_level=1,
        modality_order=["do", "read", "watch"],
        session_cap_minutes=45,
        learner_history=[],
        skill_id="skill.x",
        as_of=TODAY,
    )
    by_id = {r.candidate.resource_id: r for r in ranked}
    assert by_id["res.within"].score_breakdown["duration_fit"] == 1.0
    assert by_id["res.over"].score_breakdown["duration_fit"] < 1.0


def test_novelty_is_zero_for_a_previously_used_resource():
    ranked = score_candidates(
        [_candidate("res.a")],
        query_embedding=[],
        query_text="",
        current_level=1,
        modality_order=["do", "read", "watch"],
        session_cap_minutes=45,
        learner_history=[ResourceUsageRecord(resource_id="res.a", skill_id="skill.x", outcome="completed")],
        skill_id="skill.x",
        as_of=TODAY,
    )
    assert ranked[0].score_breakdown["novelty"] == 0.0


def test_previously_failed_resource_on_the_same_skill_is_penalized_and_ranks_lower():
    failed = _candidate("res.failed", embedding=[1.0])
    clean = _candidate("res.clean", embedding=[1.0])
    ranked = score_candidates(
        [failed, clean],
        query_embedding=[1.0],
        query_text="",
        current_level=1,
        modality_order=["do", "read", "watch"],
        session_cap_minutes=45,
        learner_history=[ResourceUsageRecord(resource_id="res.failed", skill_id="skill.x", outcome="failed")],
        skill_id="skill.x",
        as_of=TODAY,
    )
    by_id = {r.candidate.resource_id: r for r in ranked}
    assert by_id["res.failed"].score < by_id["res.clean"].score
    assert "prior_failure_penalty" in by_id["res.failed"].score_breakdown
    assert ranked[0].candidate.resource_id == "res.clean"  # ranks first despite otherwise-identical inputs


def test_prior_failure_on_a_different_skill_does_not_penalize():
    # A resource that failed for skill.y shouldn't be penalized when scored for skill.x.
    ranked = score_candidates(
        [_candidate("res.a")],
        query_embedding=[],
        query_text="",
        current_level=1,
        modality_order=["do", "read", "watch"],
        session_cap_minutes=45,
        learner_history=[ResourceUsageRecord(resource_id="res.a", skill_id="skill.y", outcome="failed")],
        skill_id="skill.x",
        as_of=TODAY,
    )
    assert "prior_failure_penalty" not in ranked[0].score_breakdown


# -- MMR duplicate removal (design §15.3's last sentence) ---------------------


def test_mmr_prefers_diversity_over_a_same_provider_and_modality_duplicate():
    from app.retrieval.ranker import RankedResource

    best = RankedResource(_candidate("res.a", provider="khanacademy", modality="read"), score=0.9, score_breakdown={})
    near_duplicate = RankedResource(_candidate("res.b", provider="khanacademy", modality="read"), score=0.85, score_breakdown={})
    diverse = RankedResource(_candidate("res.c", provider="youtube", modality="watch"), score=0.5, score_breakdown={})

    diversified = mmr_diversify([best, near_duplicate, diverse], top_k=2)
    ids = [r.candidate.resource_id for r in diversified]
    assert ids == ["res.a", "res.c"]  # near_duplicate (same provider+modality as "a") is skipped in favor of diversity


def test_mmr_falls_back_to_duplicates_when_pool_is_too_homogeneous():
    from app.retrieval.ranker import RankedResource

    a = RankedResource(_candidate("res.a", provider="khanacademy", modality="read"), score=0.9, score_breakdown={})
    b = RankedResource(_candidate("res.b", provider="khanacademy", modality="read"), score=0.8, score_breakdown={})

    diversified = mmr_diversify([a, b], top_k=2)
    # Only one (provider, modality) pair exists across the whole pool -- diversity can't be
    # satisfied, so both are still returned to fill top_k, best score first.
    assert [r.candidate.resource_id for r in diversified] == ["res.a", "res.b"]


def test_mmr_never_returns_more_than_top_k():
    from app.retrieval.ranker import RankedResource

    ranked = [RankedResource(_candidate(f"res.{i}", provider=f"p{i}"), score=1.0 - i * 0.1, score_breakdown={}) for i in range(5)]
    assert len(mmr_diversify(ranked, top_k=3)) == 3


# -- full pipeline (`recommend`) -----------------------------------------------


def test_recommend_deduplicates_repeated_resource_ids_in_input():
    c = _candidate("res.a")
    recs = recommend(
        skill_id="skill.x", objective_id=None, current_level=1, candidates=[c, c], query_embedding=[], query_text="", as_of=TODAY
    )
    assert len(recs) == 1


def test_recommend_returns_empty_list_when_nothing_is_eligible():
    broken = _candidate("res.a", link_status="broken")
    assert recommend(skill_id="skill.x", objective_id=None, current_level=1, candidates=[broken], query_embedding=[], query_text="", as_of=TODAY) == []


def test_recommend_every_result_references_a_real_input_resource_id():
    candidates = [_candidate(f"res.{i}", provider=f"p{i}") for i in range(3)]
    recs = recommend(
        skill_id="skill.x", objective_id="obj.role.x.skill.x", current_level=1, candidates=candidates, query_embedding=[], query_text="", top_k=5, as_of=TODAY
    )
    input_ids = {c.resource_id for c in candidates}
    assert {r.resource_id for r in recs} <= input_ids  # never invented -- design §15.2
    assert all(r.objective_id == "obj.role.x.skill.x" for r in recs)
    assert all(r.skill_id == "skill.x" for r in recs)
    assert all(all(r.eligibility_checks.values()) for r in recs)
    assert all(r.provenance["method"] == "hybrid" and r.provenance["retrieved_at"] for r in recs)


def test_recommend_respects_top_k():
    candidates = [_candidate(f"res.{i}", provider=f"p{i}") for i in range(5)]
    recs = recommend(skill_id="skill.x", objective_id=None, current_level=1, candidates=candidates, query_embedding=[], query_text="", top_k=2, as_of=TODAY)
    assert len(recs) == 2
