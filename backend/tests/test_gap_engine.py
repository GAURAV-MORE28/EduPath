"""Gap Engine tests (app/gap/engine.py): every status, the BLOCKED overlay,
priority/ordering, learning objectives (incl. verify-before-teach), and the
design §12.4 audit flags -- against the real curated dataset via the
`catalog_session` fixture (tests/conftest.py), mirroring
`tests/test_graph_queries.py`'s pattern so these double as a regression check
against the actual domain pack, not just a synthetic fixture.

The Gap Engine itself (`analyze_gaps`) is a pure function over plain
dataclasses -- no DB/session is touched inside it -- so most assertions here
just hand-build `LearnerSkillRecord`/`EvidenceRecord` lists and read the
result. This is deliberate (design's effort table: "Gap Engine... Pure
functions; unit-testable").
"""
from __future__ import annotations

import pytest

from app.db.models import Role, RoleRequirement, Skill, SkillEdge
from app.gap.engine import (
    BLOCKED,
    MET,
    MISSING,
    UNVERIFIED,
    WEAK,
    EvidenceRecord,
    LearnerSkillRecord,
    analyze_gaps,
    objective_id_for,
)
from app.graph.loader import GraphLoader
from app.graph.queries import SkillGraphService, UnknownRoleError
from app.repositories.catalog_repository import CatalogRepository, CatalogSnapshot


@pytest.fixture
async def graph_service(catalog_session) -> SkillGraphService:
    skill_graph = await GraphLoader(CatalogRepository(catalog_session)).load()
    return SkillGraphService(skill_graph)


@pytest.fixture
def tiny_graph_service() -> SkillGraphService:
    """A small, fully controlled hand-built graph (mirrors
    `tests/test_graph_validation.py`'s "one obvious fixture per test"
    pattern) -- built directly via `GraphLoader.build`, no DB involved.

    Real curated data (`graph_service` above) has real-world complexity: e.g.
    `skill.backpropagation` actually has *three* hard prerequisites, not one
    (chain_rule, neural_network_fundamentals, activation_functions), which
    makes it a poor fixture for isolating "exactly one blocking prerequisite"
    style assertions. This fixture is a clean linear chain instead:

        skill.a --(hard prereq of)--> skill.b --(hard prereq of)--> skill.c

    `role.test` requires b and c at level 2 (weight 3); a enters scope only
    as their hard-prerequisite ancestor, same shape as design §13.4's chain
    rule -> backpropagation -> training neural networks demo chain.
    """

    def _skill(skill_id: str, label: str) -> Skill:
        return Skill(skill_id=skill_id, label=label, kind="concept", area="test", aliases=[], description="", assessable=True)

    def _edge(from_skill: str, to_skill: str) -> SkillEdge:
        return SkillEdge(
            from_skill=from_skill,
            to_skill=to_skill,
            type="PREREQUISITE_OF",
            strength="hard",
            min_level=1,
            weight=None,
            source="curated",
            reviewed_by="test",
        )

    snapshot = CatalogSnapshot(
        skills=[_skill("skill.a", "A"), _skill("skill.b", "B"), _skill("skill.c", "C")],
        skill_edges=[_edge("skill.a", "skill.b"), _edge("skill.b", "skill.c")],
        roles=[Role(role_id="role.test", title="Test Role", description="")],
        role_requirements=[
            RoleRequirement(role_id="role.test", skill_id="skill.b", required_level=2, weight=3),
            RoleRequirement(role_id="role.test", skill_id="skill.c", required_level=2, weight=3),
        ],
        misconceptions=[],
        resources=[],
        resource_skills=[],
        practice_items=[],
        graph_meta=None,
    )
    skill_graph = GraphLoader.build(snapshot)
    return SkillGraphService(skill_graph)


def _state(skill_id: str, *, alpha: float, beta: float, tier_max: str, n_obs: int = 0) -> LearnerSkillRecord:
    return LearnerSkillRecord(skill_id=skill_id, alpha=alpha, beta=beta, tier_max=tier_max, n_obs=n_obs)


def _evidence(skill_id: str, tier: str, evidence_id: str | None = None) -> EvidenceRecord:
    return EvidenceRecord(evidence_id=evidence_id or f"ev.{skill_id}", skill_id=skill_id, tier=tier)


def _gap(result, skill_id: str):
    return next(g for g in result.gaps if g.skill_id == skill_id)


# -- statuses ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_met_when_mastery_and_tier_clear_the_level_2_gate(graph_service: SkillGraphService) -> None:
    # skill.python is required at level 2 by role.ml_engineer (>= 0.70 mastery, tier >= E2).
    states = [_state("skill.python", alpha=8, beta=2, tier_max="E2")]  # mastery = 0.8
    result = analyze_gaps("role.ml_engineer", states, [], graph_service)
    assert _gap(result, "skill.python").status == MET
    assert _gap(result, "skill.python").gap_type == "met"


@pytest.mark.asyncio
async def test_weak_when_tier_sufficient_but_mastery_below_threshold(graph_service: SkillGraphService) -> None:
    states = [_state("skill.python", alpha=1, beta=9, tier_max="E2")]  # mastery = 0.1, tier E2 is enough for L2
    result = analyze_gaps("role.ml_engineer", states, [], graph_service)
    assert _gap(result, "skill.python").status == WEAK


@pytest.mark.asyncio
async def test_weak_when_mastery_sufficient_but_tier_too_low(graph_service: SkillGraphService) -> None:
    # High mastery estimate but only E1 (documented) evidence -- L2 requires >= E2.
    states = [_state("skill.python", alpha=9, beta=1, tier_max="E1")]
    result = analyze_gaps("role.ml_engineer", states, [], graph_service)
    assert _gap(result, "skill.python").status == WEAK


@pytest.mark.asyncio
async def test_unverified_for_self_report_only(graph_service: SkillGraphService) -> None:
    states = [_state("skill.python", alpha=0.5, beta=1.0, tier_max="E0")]
    result = analyze_gaps("role.ml_engineer", states, [], graph_service)
    assert _gap(result, "skill.python").status == UNVERIFIED
    assert _gap(result, "skill.python").current_level == 0


@pytest.mark.asyncio
async def test_missing_when_no_state_at_all(graph_service: SkillGraphService) -> None:
    result = analyze_gaps("role.ml_engineer", [], [], graph_service)
    assert _gap(result, "skill.python").status == MISSING


@pytest.mark.asyncio
async def test_l2_gate_has_no_n_obs_requirement(graph_service: SkillGraphService) -> None:
    states = [_state("skill.python", alpha=8, beta=2, tier_max="E3", n_obs=0)]
    result = analyze_gaps("role.ml_engineer", states, [], graph_service)
    assert _gap(result, "skill.python").status == MET


def test_l3_tier_gate_additionally_requires_n_obs_at_least_3() -> None:
    # No skill in the curated dataset is role-required at L3 (design's
    # priors cap real role_requirement rows at level 2), so the L3 branch of
    # ARCHITECTURE_CONTRACTS.md §3's tier gate is exercised directly here.
    from app.gap.engine import _level_met

    high_mastery_few_obs = _state("skill.python", alpha=9, beta=1, tier_max="E3", n_obs=2)
    high_mastery_enough_obs = _state("skill.python", alpha=9, beta=1, tier_max="E3", n_obs=3)
    assert not _level_met(high_mastery_few_obs, 3)
    assert _level_met(high_mastery_enough_obs, 3)


# -- BLOCKED overlay -------------------------------------------------------------


@pytest.mark.asyncio
async def test_blocked_when_hard_prerequisite_is_weak(tiny_graph_service: SkillGraphService) -> None:
    states = [_state("skill.a", alpha=1, beta=9, tier_max="E1")]  # WEAK: tier ok, mastery too low
    result = analyze_gaps("role.test", states, [], tiny_graph_service)
    a = _gap(result, "skill.a")
    b = _gap(result, "skill.b")
    assert a.status == WEAK
    assert b.status == BLOCKED
    assert b.gap_type == "missing"  # raw diagnosis preserved underneath the overlay
    assert "skill.a" in b.blocked_by
    assert "skill.b" in a.root_of


@pytest.mark.asyncio
async def test_blocked_when_hard_prerequisite_is_missing(tiny_graph_service: SkillGraphService) -> None:
    result = analyze_gaps("role.test", [], [], tiny_graph_service)
    assert _gap(result, "skill.a").status == MISSING
    assert _gap(result, "skill.b").status == BLOCKED


@pytest.mark.asyncio
async def test_unverified_prerequisite_does_not_block(tiny_graph_service: SkillGraphService) -> None:
    # design §13.2: "An UNVERIFIED prerequisite does not block; it gets a probe first."
    states = [_state("skill.a", alpha=0.5, beta=1.0, tier_max="E0")]  # UNVERIFIED
    result = analyze_gaps("role.test", states, [], tiny_graph_service)
    a = _gap(result, "skill.a")
    b = _gap(result, "skill.b")
    assert a.status == UNVERIFIED
    assert b.status != BLOCKED
    assert b.status == MISSING  # no state of its own, but not blocked


@pytest.mark.asyncio
async def test_unknown_role_raises(graph_service: SkillGraphService) -> None:
    with pytest.raises(UnknownRoleError):
        analyze_gaps("role.astronaut", [], [], graph_service)


# -- scope coverage / strengths ---------------------------------------------------


@pytest.mark.asyncio
async def test_every_scope_skill_gets_exactly_one_gap_entry(graph_service: SkillGraphService) -> None:
    result = analyze_gaps("role.ml_engineer", [], [], graph_service)
    gap_ids = [g.skill_id for g in result.gaps]
    assert set(gap_ids) == result.scope_skill_ids
    assert len(gap_ids) == len(set(gap_ids))  # no duplicates


@pytest.mark.asyncio
async def test_strengths_are_exactly_the_met_subset(graph_service: SkillGraphService) -> None:
    states = [_state("skill.python", alpha=8, beta=2, tier_max="E2")]
    result = analyze_gaps("role.ml_engineer", states, [], graph_service)
    strength_ids = {s.skill_id for s in result.strengths}
    met_ids = {g.skill_id for g in result.gaps if g.status == MET}
    assert strength_ids == met_ids
    assert "skill.python" in strength_ids


@pytest.mark.asyncio
async def test_evidence_ids_attached_to_matching_gap_entry(graph_service: SkillGraphService) -> None:
    states = [_state("skill.python", alpha=1, beta=9, tier_max="E1")]
    evidence = [_evidence("skill.python", "E1", evidence_id="ev-123")]
    result = analyze_gaps("role.ml_engineer", states, evidence, graph_service)
    assert _gap(result, "skill.python").evidence_ids == ["ev-123"]
    assert _gap(result, "skill.chain_rule").evidence_ids == []


# -- ordering / layers -------------------------------------------------------------


@pytest.mark.asyncio
async def test_layers_respect_hard_prerequisite_order(graph_service: SkillGraphService) -> None:
    result = analyze_gaps("role.ml_engineer", [], [], graph_service)
    layer_of = {g.skill_id: g.ordering_layer for g in result.gaps}
    assert layer_of["skill.chain_rule"] < layer_of["skill.backpropagation"]
    assert layer_of["skill.backpropagation"] < layer_of["skill.training_neural_networks"]


@pytest.mark.asyncio
async def test_met_skills_are_not_part_of_the_unmet_layering(graph_service: SkillGraphService) -> None:
    states = [_state("skill.python", alpha=8, beta=2, tier_max="E2")]
    result = analyze_gaps("role.ml_engineer", states, [], graph_service)
    assert _gap(result, "skill.python").ordering_layer == -1
    assert "skill.python" not in {s for layer in result.layers for s in layer}


# -- learning objectives / verify-before-teach ---------------------------------------


@pytest.mark.asyncio
async def test_unverified_root_gap_becomes_a_probe_objective(tiny_graph_service: SkillGraphService) -> None:
    states = [_state("skill.a", alpha=0.5, beta=1.0, tier_max="E0")]
    result = analyze_gaps("role.test", states, [], tiny_graph_service)
    obj = next(o for o in result.objectives if o.skill_id == "skill.a")
    assert obj.objective_type == "probe"
    assert obj.from_status == UNVERIFIED
    assert "probe_items" in obj.acceptance_criteria
    assert obj.objective_id == objective_id_for("role.test", "skill.a")


@pytest.mark.asyncio
async def test_missing_root_gap_becomes_a_lesson_objective(graph_service: SkillGraphService) -> None:
    result = analyze_gaps("role.ml_engineer", [], [], graph_service)
    obj = next(o for o in result.objectives if o.skill_id == "skill.mlops_fundamentals")
    assert obj.objective_type == "lesson"
    assert obj.from_status == MISSING
    assert obj.acceptance_criteria["mastery_threshold"] == pytest.approx(0.50)  # L1 threshold


@pytest.mark.asyncio
async def test_blocked_skills_get_no_objective_yet(tiny_graph_service: SkillGraphService) -> None:
    states = [_state("skill.a", alpha=1, beta=9, tier_max="E1")]  # WEAK -> blocks skill.b
    result = analyze_gaps("role.test", states, [], tiny_graph_service)
    assert _gap(result, "skill.b").status == BLOCKED
    assert not any(o.skill_id == "skill.b" for o in result.objectives)
    assert any(o.skill_id == "skill.a" for o in result.objectives)  # the actionable root gap does


@pytest.mark.asyncio
async def test_met_skills_never_get_an_objective(graph_service: SkillGraphService) -> None:
    states = [_state("skill.python", alpha=8, beta=2, tier_max="E2")]
    result = analyze_gaps("role.ml_engineer", states, [], graph_service)
    assert not any(o.skill_id == "skill.python" for o in result.objectives)


@pytest.mark.asyncio
async def test_objective_prerequisite_chain_links_root_gap_objectives(tiny_graph_service: SkillGraphService) -> None:
    # Both a and b UNVERIFIED (neither WEAK/MISSING) -> neither blocks the
    # other, both are root gaps, and b's objective should reference a's as a
    # prerequisite.
    states = [
        _state("skill.a", alpha=0.5, beta=1.0, tier_max="E0"),
        _state("skill.b", alpha=0.5, beta=1.0, tier_max="E0"),
    ]
    result = analyze_gaps("role.test", states, [], tiny_graph_service)
    assert _gap(result, "skill.b").status == UNVERIFIED  # confirms it is not BLOCKED
    b_obj = next(o for o in result.objectives if o.skill_id == "skill.b")
    assert objective_id_for("role.test", "skill.a") in b_obj.prerequisite_objective_ids


@pytest.mark.asyncio
async def test_objectives_sorted_by_priority_descending(graph_service: SkillGraphService) -> None:
    result = analyze_gaps("role.ml_engineer", [], [], graph_service)
    priorities = [o.priority for o in result.objectives]
    assert priorities == sorted(priorities, reverse=True)


# -- audit flags (design §12.4) ---------------------------------------------------


@pytest.mark.asyncio
async def test_claimed_without_evidence_flag_for_important_e0_only_skill(graph_service: SkillGraphService) -> None:
    # skill.mlops_fundamentals is required at weight=2 (important) by role.ml_engineer.
    states = [_state("skill.mlops_fundamentals", alpha=0.5, beta=1.0, tier_max="E0")]
    result = analyze_gaps("role.ml_engineer", states, [], graph_service)
    matching = [f for f in result.audit_flags if f.flag_type == "claimed_without_evidence"]
    assert any(f.skill_id == "skill.mlops_fundamentals" for f in matching)
    assert "claimed_without_evidence" in _gap(result, "skill.mlops_fundamentals").audit_flags


@pytest.mark.asyncio
async def test_claimed_without_evidence_flag_skipped_for_low_weight_skill(graph_service: SkillGraphService) -> None:
    # skill.object_detection is weight=1 ("nice") for role.ml_engineer -- below the "important+" bar.
    states = [_state("skill.object_detection", alpha=0.5, beta=1.0, tier_max="E0")]
    result = analyze_gaps("role.ml_engineer", states, [], graph_service)
    assert not any(
        f.flag_type == "claimed_without_evidence" and f.skill_id == "skill.object_detection"
        for f in result.audit_flags
    )


@pytest.mark.asyncio
async def test_stale_or_weak_evidence_flag_for_e1_claim_at_level_2(graph_service: SkillGraphService) -> None:
    # skill.chain_rule is required at level 2 by role.ml_engineer.
    states = [_state("skill.chain_rule", alpha=1.0, beta=1.5, tier_max="E1")]
    result = analyze_gaps("role.ml_engineer", states, [], graph_service)
    matching = [f for f in result.audit_flags if f.flag_type == "stale_or_weak_evidence"]
    assert any(f.skill_id == "skill.chain_rule" for f in matching)


@pytest.mark.asyncio
async def test_claim_evidence_mismatch_full_stack_style(graph_service: SkillGraphService) -> None:
    # design §12.4's worked example, replicated with real curated data:
    # skill.math_for_ml is a PART_OF umbrella (children: chain_rule, derivatives,
    # linear_algebra_matrices, multivariable_calculus, optimization_basics).
    # Claiming the umbrella while only chain_rule has evidence should flag the
    # same "claimed the whole area, evidence covers only part of it" pattern as
    # "Full Stack claimed, evidence only for React."
    states = [
        _state("skill.math_for_ml", alpha=0.5, beta=1.0, tier_max="E0"),  # the umbrella claim
        _state("skill.chain_rule", alpha=8, beta=2, tier_max="E2"),  # evidence for one child only
    ]
    result = analyze_gaps("role.ml_engineer", states, [], graph_service)
    matching = [f for f in result.audit_flags if f.flag_type == "claim_evidence_mismatch"]
    assert matching, "expected a claim_evidence_mismatch flag on the math_for_ml umbrella claim"
    flag = matching[0]
    assert flag.skill_id == "skill.math_for_ml"
    assert "skill.chain_rule" in flag.related_skill_ids
    assert "skill.derivatives" in flag.related_skill_ids  # required by role.ml_engineer, no evidence given


@pytest.mark.asyncio
async def test_claim_evidence_mismatch_not_flagged_without_a_claim_on_the_parent(
    graph_service: SkillGraphService,
) -> None:
    # Evidence for chain_rule alone, with no claim on the math_for_ml umbrella
    # itself, should not trigger the mismatch rule (design §12.4: it is "a
    # claim of a parent skill... while evidence covers only some children").
    states = [_state("skill.chain_rule", alpha=8, beta=2, tier_max="E2")]
    result = analyze_gaps("role.ml_engineer", states, [], graph_service)
    assert not any(f.flag_type == "claim_evidence_mismatch" for f in result.audit_flags)


# -- unsupported / unknown skill handling -----------------------------------------


@pytest.mark.asyncio
async def test_evidence_for_a_skill_outside_role_scope_is_ignored_not_erroring(
    graph_service: SkillGraphService,
) -> None:
    # skill.excel is real but not part of role.ml_engineer's subgraph at all.
    states = [_state("skill.excel", alpha=8, beta=2, tier_max="E2")]
    result = analyze_gaps("role.ml_engineer", states, [], graph_service)
    assert "skill.excel" not in {g.skill_id for g in result.gaps}


@pytest.mark.asyncio
async def test_evidence_for_an_unknown_skill_id_does_not_crash_the_report(graph_service: SkillGraphService) -> None:
    # A stale/unsupported skill_id (e.g. from a since-renamed catalog) must be
    # skipped gracefully, not raise, so one bad row can't take down the whole
    # gap report.
    states = [
        _state("skill.this_skill_id_does_not_exist", alpha=8, beta=2, tier_max="E2"),
        _state("skill.python", alpha=8, beta=2, tier_max="E2"),
    ]
    result = analyze_gaps("role.ml_engineer", states, [], graph_service)
    assert _gap(result, "skill.python").status == MET
    assert not any(f.skill_id == "skill.this_skill_id_does_not_exist" for f in result.audit_flags)
