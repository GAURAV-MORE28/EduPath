"""Evaluation: gap correctness, prerequisite validity, retrieval quality, plan validity
(design §32.2 rows 3-5).

*Gap correctness* is measured against an **independent oracle** written from design §13.3 / the tier
gate (ARCHITECTURE_CONTRACTS.md §3-§4) -- not against the engine's own helpers -- over randomized
learners on all three curated roles. *Prerequisite validity* checks the graph and the layers/plans
derived from it. *Retrieval* is scored against the catalog's own TARGETS edges (graded by level fit)
with a vector-only baseline for the graph-anchoring ablation. *Plan validity* is checked over
diverse learner personas through the real API.
"""
from __future__ import annotations

import math
import random

import networkx as nx
import pytest

from app.core.thresholds import LEVEL_MASTERY_THRESHOLD, LEVEL_MIN_N_OBS, LEVEL_TIER_REQUIRED, TIER_ORDER
from app.gap.engine import LearnerSkillRecord, analyze_gaps
from app.gateway.embedding_gateway import DegradedEmbeddingGateway
from app.graph.loader import GraphLoader
from app.graph.queries import SkillGraphService
from app.repositories.catalog_repository import CatalogRepository
from app.retrieval.ranker import _cosine
from app.retrieval.service import ResourceRetrievalService
from tests.evaluation.metrics import record

pytestmark = pytest.mark.asyncio

ROLES = ["role.ml_engineer", "role.data_analyst", "role.backend_developer"]


@pytest.fixture
async def graph_service(catalog_session) -> SkillGraphService:
    return SkillGraphService(await GraphLoader(CatalogRepository(catalog_session)).load())


# -- gap correctness ---------------------------------------------------------------------------------------------


def _tier_at_least(tier: str, minimum: str) -> bool:
    return TIER_ORDER.index(tier) >= TIER_ORDER.index(minimum)


def _oracle_raw_status(rec: LearnerSkillRecord | None, required_level: int) -> str:
    """design §13.3 / tier gate, re-derived independently: no state -> MISSING; the level is met when the
    tier clears the level's minimum, the Beta-count estimate clears its threshold, and (L3) enough
    assessed items exist; otherwise WEAK if there is at least E1 evidence, else UNVERIFIED (E0 = a claim)."""
    if rec is None:
        return "MISSING"
    estimate = rec.alpha / (rec.alpha + rec.beta)
    met = (
        _tier_at_least(rec.tier_max, LEVEL_TIER_REQUIRED[required_level])
        and estimate >= LEVEL_MASTERY_THRESHOLD[required_level]
        and rec.n_obs >= LEVEL_MIN_N_OBS.get(required_level, 0)
    )
    if met:
        return "MET"
    return "WEAK" if _tier_at_least(rec.tier_max, "E1") else "UNVERIFIED"


def _random_learner(rng: random.Random, skill_ids: list[str]) -> list[LearnerSkillRecord]:
    profiles = [
        None, None, None,  # most skills untouched
        ("E0", 0.5, 1.0, 0),  # a bare claim
        ("E1", 1.0, 1.5, 0),  # documented, weak
        ("E2", 9.0, 1.0, 0),  # artifact-backed and strong
        ("E3", 9.0, 1.0, 5),  # assessed in-system, strong
        ("E3", 2.0, 6.0, 4),  # assessed, poor
    ]
    records = []
    for sid in skill_ids:
        p = rng.choice(profiles)
        if p is not None:
            records.append(LearnerSkillRecord(skill_id=sid, alpha=p[1], beta=p[2], tier_max=p[0], n_obs=p[3]))
    return records


async def test_gap_statuses_match_an_independent_oracle_on_randomized_learners(graph_service):
    rng = random.Random(20260920)
    checked = mismatches = blocked_checked = 0
    details: list[str] = []
    for role_id in ROLES:
        scope = sorted(graph_service.role_subgraph(role_id).skill_ids)
        for _ in range(25):
            records = _random_learner(rng, scope)
            state = {r.skill_id: r for r in records}
            result = analyze_gaps(role_id, records, [], graph_service)

            required = {g.skill_id: g.required_level for g in result.gaps}
            required.update({s.skill_id: s.required_level for s in result.strengths})
            raw = {sid: _oracle_raw_status(state.get(sid), required[sid]) for sid in required}
            reported = {g.skill_id: g.status for g in result.gaps}
            reported.update({s.skill_id: "MET" for s in result.strengths})

            for sid in required:
                hard_parents = [p for p in graph_service.direct_prerequisites(sid, include_soft=False) if p in required]
                expected = "BLOCKED" if raw[sid] != "MET" and any(raw[p] in ("WEAK", "MISSING") for p in hard_parents) else raw[sid]
                checked += 1
                blocked_checked += expected == "BLOCKED"
                if reported.get(sid) != expected:
                    mismatches += 1
                    if len(details) < 5:
                        details.append(f"{role_id} {sid}: engine={reported.get(sid)} oracle={expected} (raw {raw[sid]})")
    accuracy = 1 - mismatches / checked
    record("Gap", "status accuracy vs independent oracle", accuracy, "1.00", f"{checked} skill statuses ({blocked_checked} BLOCKED) over 75 random learners x 3 roles")
    assert mismatches == 0, details


async def test_gap_ordering_objectives_and_verify_before_teach_are_consistent(graph_service):
    rng = random.Random(7)
    violations = probe_errors = 0
    total_edges = total_objectives = 0
    for role_id in ROLES:
        scope = sorted(graph_service.role_subgraph(role_id).skill_ids)
        for _ in range(20):
            result = analyze_gaps(role_id, _random_learner(rng, scope), [], graph_service)
            layer = {g.skill_id: g.ordering_layer for g in result.gaps if g.status != "MET"}
            for p, s in result.prerequisite_edges:  # no gap is ordered before (or with) its unmet hard prerequisite gap
                if p in layer and s in layer:
                    total_edges += 1
                    violations += layer[p] >= layer[s]
            by_skill = {g.skill_id: g for g in result.gaps}
            met = {s.skill_id for s in result.strengths}
            ids = {o.objective_id for o in result.objectives}
            for o in result.objectives:
                total_objectives += 1
                assert o.skill_id not in met, "a MET skill never becomes an objective"
                assert by_skill[o.skill_id].status != "BLOCKED", "a BLOCKED skill is never an objective (its root is)"
                assert set(o.prerequisite_objective_ids) <= ids
                if o.from_status == "UNVERIFIED":
                    probe_errors += o.objective_type != "probe"  # verify-before-teach: never a beginner lesson
                else:
                    probe_errors += o.objective_type != "lesson"
    record("Gap", "prerequisite consistency (ordering layers)", 1 - violations / max(total_edges, 1), "1.00", f"{total_edges} prerequisite edges between open gaps")
    record("Gap", "verify-before-teach objective typing", 1 - probe_errors / total_objectives, "1.00", f"{total_objectives} objectives")
    assert violations == 0 and probe_errors == 0


async def test_gap_analysis_is_deterministic(graph_service):
    rng = random.Random(3)
    scope = sorted(graph_service.role_subgraph("role.ml_engineer").skill_ids)
    records = _random_learner(rng, scope)
    runs = [analyze_gaps("role.ml_engineer", records, [], graph_service) for _ in range(3)]
    fingerprint = lambda r: ([(g.skill_id, g.status, g.priority, g.ordering_layer) for g in r.gaps], [(o.objective_id, o.priority) for o in r.objectives])  # noqa: E731
    assert fingerprint(runs[0]) == fingerprint(runs[1]) == fingerprint(runs[2])


# -- prerequisite validity ----------------------------------------------------------------------------------------


async def test_the_prerequisite_graph_is_a_valid_dag_with_no_dangling_edges(catalog_session, graph_service):
    catalog = CatalogRepository(catalog_session)
    snapshot = await catalog.snapshot() if hasattr(catalog, "snapshot") else None
    skill_ids = {s.skill_id for s in await catalog.get_all_skills()}
    assert graph_service.is_dag()
    hard = nx.DiGraph()
    dangling = 0
    from sqlalchemy import select

    from app.db.models import SkillEdge

    for e in (await catalog_session.execute(select(SkillEdge))).scalars().all():
        if e.from_skill not in skill_ids or e.to_skill not in skill_ids:
            dangling += 1
        if e.type == "PREREQUISITE_OF" and e.strength == "hard":
            hard.add_edge(e.from_skill, e.to_skill)
    assert dangling == 0 and nx.is_directed_acyclic_graph(hard)
    # every role-required skill's whole hard-prerequisite closure is inside that role's subgraph
    for role_id in ROLES:
        sub = graph_service.role_subgraph(role_id)
        for sid in sub.skill_ids:
            assert graph_service.hard_ancestors(sid) <= sub.skill_ids
    record("Prerequisites", "graph: acyclic hard-prerequisite DAG, no dangling edges", 1.0, "1.00", f"{hard.number_of_edges()} hard edges over {hard.number_of_nodes()} skills")
    _ = snapshot


# -- retrieval quality -------------------------------------------------------------------------------------------------


def _ndcg(gains: list[float], ideal: list[float], k: int) -> float:
    dcg = sum(g / math.log2(i + 2) for i, g in enumerate(gains[:k]))
    idcg = sum(g / math.log2(i + 2) for i, g in enumerate(sorted(ideal, reverse=True)[:k]))
    return dcg / idcg if idcg else 0.0


async def test_retrieval_quality_eligibility_and_graph_anchoring_ablation(catalog_session, graph_service):
    from sqlalchemy import select

    from app.db.models import Resource, ResourceSkill

    catalog = CatalogRepository(catalog_session)
    embedder = DegradedEmbeddingGateway()
    service = ResourceRetrievalService(catalog, graph_service, embedder)
    resources = {r.resource_id: r for r in (await catalog_session.execute(select(Resource))).scalars().all()}
    targets: dict[str, dict[str, tuple[int, int]]] = {}
    for rs in (await catalog_session.execute(select(ResourceSkill))).scalars().all():
        targets.setdefault(rs.skill_id, {})[rs.resource_id] = (rs.level_from, rs.level_to)

    role_skills = sorted({sid for role in ROLES for sid in graph_service.role_subgraph(role).skill_ids if sid in targets})
    assert len(role_skills) > 50

    everything = {s.skill_id for s in await catalog.get_all_skills()}
    K = 3
    p_at_k, r_at_k, mrr, ndcg, violations, covered, baseline_p, returned = [], [], [], [], 0, 0, [], []
    uncovered: list[str] = []
    embeddings = {rid: await embedder.embed(f"{r.title}. {r.learning_objective_text}") for rid, r in resources.items()}
    for sid in role_skills:
        relevant = set(targets[sid])
        met = set(everything)  # best case for the prerequisite filter (a resource's own prerequisites need not be graph ancestors)
        recs = await service.recommend_for_skill(skill_id=sid, current_level=0, met_skill_ids=met, session_cap_minutes=10_000, top_k=K)
        ids = [r.resource_id for r in recs]
        if ids:
            covered += 1
        else:
            uncovered.append(sid)
        for rec in recs:  # eligibility violations: unknown resource, dead link, or not TARGETing this skill
            r = resources.get(rec.resource_id)
            violations += r is None or r.link_status != "ok" or rec.resource_id not in relevant
        hits = [i for i in ids if i in relevant]
        p_at_k.append(len(hits) / len(ids) if ids else 0.0)  # true precision over what was returned
        returned.append(len(ids))
        r_at_k.append(len(hits) / min(len(relevant), K) if ids else 0.0)
        mrr.append(next((1 / (i + 1) for i, rid in enumerate(ids) if rid in relevant), 0.0))
        # graded relevance: a resource whose level band starts at the learner's level is the best fit
        gains = [2.0 if targets[sid].get(i, (9, 9))[0] == 0 else 1.0 if i in relevant else 0.0 for i in ids]
        ndcg.append(_ndcg(gains, [2.0 if lf == 0 else 1.0 for lf, _lt in targets[sid].values()], K))

        # baseline: vector-only over the whole catalog, no graph anchoring, no eligibility filter
        skill = graph_service.get_skill(sid)
        q = await embedder.embed(f"{skill.label}. {skill.description}")
        top = sorted(embeddings, key=lambda rid: _cosine(q, embeddings[rid]), reverse=True)[:K]
        baseline_p.append(sum(rid in relevant for rid in top) / K)

    n = len(role_skills)
    record("Retrieval", f"precision@{K}", sum(p_at_k) / n, "report", f"{n} role skills; graph-anchored + eligibility-filtered; mean {sum(returned) / n:.1f} results/skill")
    record("Retrieval", f"recall@{K}", sum(r_at_k) / n, "report")
    record("Retrieval", "MRR", sum(mrr) / n, "report")
    record("Retrieval", f"NDCG@{K}", sum(ndcg) / n, "report", "graded by level fit")
    record("Retrieval", "eligibility-violation rate", violations, "0", "unknown resource / broken link / not targeting the skill")
    record("Retrieval", "coverage (>=1 eligible resource, session cap lifted)", covered / n, "report", f"uncovered: {uncovered}" if uncovered else "")
    record("Retrieval", f"baseline precision@{K} (vector-only, no graph)", sum(baseline_p) / n, "report", "ablation: the value of graph anchoring")
    assert violations == 0
    assert sum(p_at_k) / n > sum(baseline_p) / n, "graph anchoring must not do worse than the vector-only baseline"
    assert covered / n >= 0.9, uncovered


async def test_session_cap_coverage_is_reported(catalog_session, graph_service):
    """At the default 45-minute session cap (design §14.3's hard duration filter), how many role skills still
    have an eligible lesson? Reported, not asserted -- see FINAL_IMPLEMENTATION_STATUS.md 'Known limitations'."""
    from sqlalchemy import select

    from app.db.models import ResourceSkill

    service = ResourceRetrievalService(CatalogRepository(catalog_session), graph_service, DegradedEmbeddingGateway())
    everything = {s.skill_id for s in await CatalogRepository(catalog_session).get_all_skills()}
    with_resources = {rs.skill_id for rs in (await catalog_session.execute(select(ResourceSkill))).scalars().all()}
    skills = sorted({sid for role in ROLES for sid in graph_service.role_subgraph(role).skill_ids if sid in with_resources})
    covered = 0
    for sid in skills:
        recs = await service.recommend_for_skill(skill_id=sid, current_level=0, met_skill_ids=everything, top_k=3)
        covered += bool(recs)
    record("Retrieval", "coverage at the default 45-min session cap", covered / len(skills), "report", f"{covered}/{len(skills)} role skills")
