"""The deterministic core of the Resource Retriever/Ranker (design §14.3
pipeline steps 2-5, §15.3's ranking formula). A pure module: no DB session,
no gateway/LLM call anywhere below `recommend()` -- callers (`service.py`)
fetch rows and compute the query embedding first, then hand in plain
dataclasses. This is what makes the whole pipeline unit-testable with
hand-built fixtures (same shape as `app/gap/engine.py`).

Pipeline (design §14.3 points 2-4, §15.3):
  1. Eligibility filter (hard) -- `filter_eligible`.
  2. Hybrid retrieval: dense (cosine over `EmbeddingGateway` vectors) +
     keyword (token overlap over title/learning_objective_text), fused by
     Reciprocal Rank Fusion -- `_reciprocal_rank_fusion`.
  3. Deterministic ranking (design §15.3's weighted formula) -- `score_candidates`.
  4. MMR diversification (same-provider-and-modality de-duplication, design
     §15.3's last sentence) -- `mmr_diversify`.

No LLM anywhere in this module (ARCHITECTURE_CONTRACTS.md §2: this is a
deterministic service, not one of the five agents) -- resources are never
invented; every `ResourceRecommendation` carries a real `resource_id` from
the candidate list handed in.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from app.core.thresholds import (
    DEFAULT_SESSION_CAP_MINUTES,
    RESOURCE_PRIOR_FAILURE_PENALTY,
    RESOURCE_QUALITY_RECENCY_FLOOR_FACTOR,
    RESOURCE_QUALITY_RECENCY_FRESH_DAYS,
    RESOURCE_QUALITY_RECENCY_STALE_DAYS,
    RESOURCE_QUALITY_RECENCY_STALE_FACTOR,
    RESOURCE_QUALITY_TIER_BASE,
    RESOURCE_RANK_WEIGHTS,
    RRF_K,
)

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(text.lower()))


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    # EmbeddingGateway vectors are L2-normalized, so dot product == cosine similarity
    # (same convention as app/profiling/skill_normalizer.py's `_cosine`).
    return sum(x * y for x, y in zip(a, b))


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResourceCandidate:
    """The subset of `Resource` + its `ResourceSkill` (`TARGETS`) edge for
    one particular skill the Retriever needs (design §15.1). `level_from`/
    `level_to` come from the `TARGETS` edge, not `Resource.difficulty` --
    design §15.1: `skill_targets[] = (skill_id, level_from, level_to)`, the
    field the eligibility filter's "difficulty band" check is defined over.
    """

    resource_id: str
    title: str
    url: str
    provider: str
    type: str
    duration_min: int
    modality: str  # watch | read | do
    prerequisite_skill_ids: list[str]
    learning_objective_text: str
    language: str
    curation_tier: str  # curated | community | unvetted
    last_verified_at: date | None
    link_status: str  # ok | redirected | broken
    embedding: list[float] | None
    level_from: int
    level_to: int


@dataclass(frozen=True)
class ResourceUsageRecord:
    """A learner's prior interaction with a resource -- design §15.3's
    `novelty` ("not previously used") and `penalty_if_prior_failure` ("a
    resource followed by failure on the same skill") inputs. No
    `LearningActivity`/`Assessment` table exists yet to source this from
    live data (Phase 7/8) -- this type exists so the ranking algorithm is
    complete and testable now; a real caller supplies real history once one
    of those phases writes it.
    """

    resource_id: str
    skill_id: str
    outcome: str  # "completed" | "failed" | "in_progress"


@dataclass
class RankedResource:
    candidate: ResourceCandidate
    score: float
    score_breakdown: dict[str, float]


@dataclass
class ResourceRecommendation:
    """design §25.2's `ResourceRecommendation` schema."""

    resource_id: str
    objective_id: str | None
    skill_id: str
    score: float
    score_breakdown: dict[str, float]
    eligibility_checks: dict[str, bool]
    provenance: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 1. Eligibility filter (design §14.3 point 2)
# ---------------------------------------------------------------------------


def eligibility_checks(
    candidate: ResourceCandidate,
    *,
    current_level: int,
    met_skill_ids: set[str],
    session_cap_minutes: int,
    language: str,
    excluded_modalities: set[str],
    sessionizable: bool = False,
) -> dict[str, bool]:
    """Every named hard-filter condition from design §14.3 point 2, except
    "all resource prerequisites are MET **or scheduled earlier**" -- no
    Planner/schedule exists yet to know what's "earlier", so this only
    checks MET (a documented simplification, not a silent omission).

    `sessionizable=True` (Stage 2, `app/planning/sessions.py`): the caller will divide a resource longer than
    `session_cap_minutes` into study sessions that each fit the cap, so length alone no longer makes it ineligible
    (`duration_ok` then only requires a positive duration). The default keeps the original whole-resource behaviour."""
    return {
        "link_ok": candidate.link_status == "ok",
        "level_band_ok": candidate.level_from <= current_level + 1 and candidate.level_to >= current_level,
        "prerequisites_met": all(p in met_skill_ids for p in candidate.prerequisite_skill_ids),
        "duration_ok": candidate.duration_min > 0 if sessionizable else candidate.duration_min <= session_cap_minutes,
        "language_ok": not language or not candidate.language or candidate.language == language,
        "modality_ok": candidate.modality not in excluded_modalities,
    }


def filter_eligible(
    candidates: list[ResourceCandidate],
    *,
    current_level: int,
    met_skill_ids: set[str],
    session_cap_minutes: int,
    language: str,
    excluded_modalities: set[str],
    sessionizable: bool = False,
) -> list[ResourceCandidate]:
    return [
        c
        for c in candidates
        if all(
            eligibility_checks(
                c,
                current_level=current_level,
                met_skill_ids=met_skill_ids,
                session_cap_minutes=session_cap_minutes,
                language=language,
                excluded_modalities=excluded_modalities,
                sessionizable=sessionizable,
            ).values()
        )
    ]


# ---------------------------------------------------------------------------
# 2. Hybrid retrieval: dense + keyword, fused by RRF (design §14.3 point 3)
# ---------------------------------------------------------------------------


def _reciprocal_rank_fusion(rankings: list[list[str]], k: int = RRF_K) -> dict[str, float]:
    scores: dict[str, float] = {}
    for ranking in rankings:
        for i, resource_id in enumerate(ranking):
            scores[resource_id] = scores.get(resource_id, 0.0) + 1.0 / (k + i + 1)
    return scores


def _hybrid_relevance(candidates: list[ResourceCandidate], query_embedding: list[float], query_tokens: set[str]) -> dict[str, float]:
    """RRF-fused, [0, 1]-normalized relevance per resource_id (design
    §15.3's `relevance` component)."""
    if not candidates:
        return {}

    dense_ranking = sorted(candidates, key=lambda c: _cosine(query_embedding, c.embedding or []), reverse=True)
    keyword_ranking = sorted(
        candidates,
        key=lambda c: len(query_tokens & _tokenize(f"{c.title} {c.title} {c.learning_objective_text}")),
        reverse=True,
    )
    rrf = _reciprocal_rank_fusion([[c.resource_id for c in dense_ranking], [c.resource_id for c in keyword_ranking]])
    max_score = max(rrf.values()) if rrf else 0.0
    if max_score == 0.0:
        return dict.fromkeys(rrf, 0.0)
    return {resource_id: score / max_score for resource_id, score in rrf.items()}


# ---------------------------------------------------------------------------
# 3. Deterministic ranking (design §15.3)
# ---------------------------------------------------------------------------


def _level_fit(candidate: ResourceCandidate, current_level: int) -> float:
    # design comment: "-> 1.0 when level_from == current_level"; linear falloff either side.
    return max(0.0, 1.0 - 0.5 * abs(candidate.level_from - current_level))


def _quality(candidate: ResourceCandidate, as_of: date) -> float:
    base = RESOURCE_QUALITY_TIER_BASE.get(candidate.curation_tier, RESOURCE_QUALITY_TIER_BASE["unvetted"])
    if candidate.last_verified_at is None:
        recency = RESOURCE_QUALITY_RECENCY_FLOOR_FACTOR
    else:
        age_days = (as_of - candidate.last_verified_at).days
        if age_days <= RESOURCE_QUALITY_RECENCY_FRESH_DAYS:
            recency = 1.0
        elif age_days <= RESOURCE_QUALITY_RECENCY_STALE_DAYS:
            recency = RESOURCE_QUALITY_RECENCY_STALE_FACTOR
        else:
            recency = RESOURCE_QUALITY_RECENCY_FLOOR_FACTOR
    return base * recency


def _modality_pref(candidate: ResourceCandidate, modality_order: list[str]) -> float:
    if candidate.modality not in modality_order:
        return 0.0
    return 1.0 - modality_order.index(candidate.modality) / len(modality_order)


def _duration_fit(candidate: ResourceCandidate, session_cap_minutes: int) -> float:
    if candidate.duration_min <= session_cap_minutes or session_cap_minutes <= 0:
        return 1.0
    overshoot = (candidate.duration_min - session_cap_minutes) / session_cap_minutes
    return max(0.0, 1.0 - overshoot)


def score_candidates(
    eligible: list[ResourceCandidate],
    *,
    query_embedding: list[float],
    query_text: str,
    current_level: int,
    modality_order: list[str],
    session_cap_minutes: int,
    learner_history: list[ResourceUsageRecord],
    skill_id: str,
    as_of: date,
) -> list[RankedResource]:
    query_tokens = _tokenize(query_text)
    relevance_by_id = _hybrid_relevance(eligible, query_embedding, query_tokens)

    used_ids = {h.resource_id for h in learner_history}
    failed_ids = {h.resource_id for h in learner_history if h.outcome == "failed" and h.skill_id == skill_id}

    ranked: list[RankedResource] = []
    for c in eligible:
        breakdown = {
            "level_fit": _level_fit(c, current_level),
            "quality": _quality(c, as_of),
            "modality_pref": _modality_pref(c, modality_order),
            "relevance": relevance_by_id.get(c.resource_id, 0.0),
            "duration_fit": _duration_fit(c, session_cap_minutes),
            "novelty": 0.0 if c.resource_id in used_ids else 1.0,
        }
        penalty = RESOURCE_PRIOR_FAILURE_PENALTY if c.resource_id in failed_ids else 0.0
        score = sum(RESOURCE_RANK_WEIGHTS[k] * v for k, v in breakdown.items()) - penalty
        if penalty:
            breakdown["prior_failure_penalty"] = -penalty
        ranked.append(RankedResource(candidate=c, score=score, score_breakdown=breakdown))

    ranked.sort(key=lambda r: r.score, reverse=True)
    return ranked


# ---------------------------------------------------------------------------
# 4. MMR diversification (design §15.3: "removes near-duplicates -- same
#    provider and modality -- from the top-K")
# ---------------------------------------------------------------------------


def mmr_diversify(ranked: list[RankedResource], top_k: int) -> list[RankedResource]:
    """Greedy diversification: prefer at most one resource per
    (provider, modality) pair, highest score first, while there are enough
    distinct pairs to fill `top_k`; falls back to the next-best leftovers
    (still score-ordered) only if the eligible pool is too homogeneous to
    fill `top_k` any other way -- never returns fewer than
    `min(top_k, len(ranked))` items over a diversity constraint.
    """
    selected: list[RankedResource] = []
    seen_pairs: set[tuple[str, str]] = set()
    leftovers: list[RankedResource] = []

    for r in ranked:
        pair = (r.candidate.provider, r.candidate.modality)
        if pair in seen_pairs:
            leftovers.append(r)
            continue
        selected.append(r)
        seen_pairs.add(pair)
        if len(selected) == top_k:
            return selected

    for r in leftovers:
        if len(selected) == top_k:
            break
        selected.append(r)
    return selected


# ---------------------------------------------------------------------------
# Orchestration of the pure pipeline
# ---------------------------------------------------------------------------


def recommend(
    *,
    skill_id: str,
    objective_id: str | None,
    current_level: int,
    candidates: list[ResourceCandidate],
    query_embedding: list[float],
    query_text: str,
    met_skill_ids: set[str] | None = None,
    modality_order: list[str] | None = None,
    language: str = "",
    session_cap_minutes: int = DEFAULT_SESSION_CAP_MINUTES,
    excluded_modalities: set[str] | None = None,
    learner_history: list[ResourceUsageRecord] | None = None,
    top_k: int = 5,
    as_of: date | None = None,
    sessionizable: bool = False,
) -> list[ResourceRecommendation]:
    """The full design §14.3 pipeline (steps 2-5), pure and synchronous.
    Resources are never invented here: every returned recommendation's
    `resource_id` is one handed in via `candidates` (design §15.2: "no
    resource may enter a plan unless its ID exists in the catalog")."""
    met_skill_ids = met_skill_ids or set()
    modality_order = modality_order or ["do", "read", "watch"]
    excluded_modalities = excluded_modalities or set()
    learner_history = learner_history or []
    as_of = as_of or date.today()

    # Dedupe by resource_id (first occurrence wins) before anything else --
    # a caller could hand in the same resource twice (e.g. it targets the
    # skill via more than one TARGETS row in a hypothetical future schema).
    deduped: list[ResourceCandidate] = []
    seen_ids: set[str] = set()
    for c in candidates:
        if c.resource_id in seen_ids:
            continue
        seen_ids.add(c.resource_id)
        deduped.append(c)

    eligible = filter_eligible(
        deduped,
        current_level=current_level,
        met_skill_ids=met_skill_ids,
        session_cap_minutes=session_cap_minutes,
        language=language,
        excluded_modalities=excluded_modalities,
        sessionizable=sessionizable,
    )
    if not eligible:
        return []

    ranked = score_candidates(
        eligible,
        query_embedding=query_embedding,
        query_text=query_text,
        current_level=current_level,
        modality_order=modality_order,
        session_cap_minutes=session_cap_minutes,
        learner_history=learner_history,
        skill_id=skill_id,
        as_of=as_of,
    )
    diversified = mmr_diversify(ranked, top_k=top_k)

    retrieved_at = datetime.now(timezone.utc).isoformat()
    return [
        ResourceRecommendation(
            resource_id=r.candidate.resource_id,
            objective_id=objective_id,
            skill_id=skill_id,
            score=r.score,
            score_breakdown=r.score_breakdown,
            eligibility_checks=eligibility_checks(
                r.candidate,
                current_level=current_level,
                met_skill_ids=met_skill_ids,
                session_cap_minutes=session_cap_minutes,
                language=language,
                excluded_modalities=excluded_modalities,
                sessionizable=sessionizable,
            ),
            provenance={"method": "hybrid", "retrieved_at": retrieved_at},
        )
        for r in diversified
    ]
