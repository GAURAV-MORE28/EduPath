"""SkillGraphService tests (app/graph/queries.py): prerequisite traversal,
ancestor/descendant queries, topological ordering, role subgraph generation,
prerequisite-path explanation — against the real curated dataset via the
`catalog_session` fixture (tests/conftest.py).
"""
from __future__ import annotations

import networkx as nx
import pytest

from app.graph.loader import GraphLoader
from app.graph.queries import SkillGraphService, UnknownRoleError, UnknownSkillError
from app.repositories.catalog_repository import CatalogRepository


@pytest.fixture
async def graph_service(catalog_session) -> SkillGraphService:
    skill_graph = await GraphLoader(CatalogRepository(catalog_session)).load()
    return SkillGraphService(skill_graph)


@pytest.mark.asyncio
async def test_is_dag(graph_service: SkillGraphService) -> None:
    assert graph_service.is_dag()


@pytest.mark.asyncio
async def test_hard_ancestors_of_backpropagation_include_chain_rule(graph_service: SkillGraphService) -> None:
    # design §13.4 worked example: chain rule is a prerequisite of backpropagation.
    ancestors = graph_service.hard_ancestors("skill.backpropagation")
    assert "skill.chain_rule" in ancestors
    assert "skill.derivatives" in ancestors
    assert "skill.backpropagation" not in ancestors  # a skill is not its own ancestor


@pytest.mark.asyncio
async def test_hard_descendants_of_chain_rule_include_backpropagation(graph_service: SkillGraphService) -> None:
    descendants = graph_service.hard_descendants("skill.chain_rule")
    assert "skill.backpropagation" in descendants


@pytest.mark.asyncio
async def test_ancestors_and_descendants_are_disjoint_for_a_mid_graph_skill(graph_service: SkillGraphService) -> None:
    anc = graph_service.hard_ancestors("skill.backpropagation")
    desc = graph_service.hard_descendants("skill.backpropagation")
    assert anc.isdisjoint(desc)


@pytest.mark.asyncio
async def test_unknown_skill_raises(graph_service: SkillGraphService) -> None:
    with pytest.raises(UnknownSkillError):
        graph_service.hard_ancestors("skill.does_not_exist")
    with pytest.raises(UnknownSkillError):
        graph_service.get_skill("skill.does_not_exist")


@pytest.mark.asyncio
async def test_direct_prerequisites_excludes_soft_when_asked(graph_service: SkillGraphService) -> None:
    all_prereqs = set(graph_service.direct_prerequisites("skill.backpropagation", include_soft=True))
    hard_only = set(graph_service.direct_prerequisites("skill.backpropagation", include_soft=False))
    assert hard_only <= all_prereqs


@pytest.mark.asyncio
async def test_topological_order_respects_hard_prerequisites(graph_service: SkillGraphService) -> None:
    order = graph_service.topological_order()
    position = {s: i for i, s in enumerate(order)}
    assert position["skill.chain_rule"] < position["skill.backpropagation"]
    assert position["skill.derivatives"] < position["skill.chain_rule"]


@pytest.mark.asyncio
async def test_topological_order_over_subset(graph_service: SkillGraphService) -> None:
    subset = {"skill.chain_rule", "skill.backpropagation", "skill.derivatives"}
    order = graph_service.topological_order(subset)
    assert set(order) == subset
    assert order.index("skill.derivatives") < order.index("skill.chain_rule") < order.index("skill.backpropagation")


@pytest.mark.asyncio
async def test_topological_layers_partition_and_respect_order(graph_service: SkillGraphService) -> None:
    subset = {"skill.chain_rule", "skill.backpropagation", "skill.derivatives"}
    layers = graph_service.topological_layers(subset)
    flat = [s for layer in layers for s in layer]
    assert set(flat) == subset
    layer_of = {s: i for i, layer in enumerate(layers) for s in layer}
    assert layer_of["skill.derivatives"] < layer_of["skill.chain_rule"] < layer_of["skill.backpropagation"]


@pytest.mark.asyncio
async def test_role_subgraph_closure_includes_hard_prerequisites(graph_service: SkillGraphService) -> None:
    rs = graph_service.role_subgraph("role.ml_engineer")
    assert "skill.chain_rule" in rs.required_skill_ids
    assert "skill.derivatives" in rs.skill_ids  # prerequisite of chain_rule, pulled in by closure
    assert rs.required_skill_ids <= rs.skill_ids
    assert rs.required_levels["skill.chain_rule"] >= 1
    assert rs.weights["skill.chain_rule"] >= 1


@pytest.mark.asyncio
async def test_role_subgraph_unknown_role_raises(graph_service: SkillGraphService) -> None:
    with pytest.raises(UnknownRoleError):
        graph_service.role_subgraph("role.astronaut")


@pytest.mark.asyncio
async def test_role_subgraph_is_internally_a_dag(graph_service: SkillGraphService) -> None:
    rs = graph_service.role_subgraph("role.data_analyst")
    sub = graph_service._hard_graph.subgraph(rs.skill_ids)
    assert nx.is_directed_acyclic_graph(sub)


@pytest.mark.asyncio
async def test_explain_skill_path_to_role_requirement(graph_service: SkillGraphService) -> None:
    # design §14.4 worked example: chain rule -> backpropagation -> training neural networks
    path = graph_service.explain_skill_path("skill.derivatives", "role.ml_engineer")
    assert path is not None
    ids = [step.skill_id for step in path]
    assert ids[0] == "skill.derivatives"
    assert ids[-1] in graph_service.role_subgraph("role.ml_engineer").required_skill_ids
    # every consecutive pair must be a real hard-prerequisite edge
    for a, b in zip(ids, ids[1:]):
        assert b in graph_service.direct_dependents(a, include_soft=False)


@pytest.mark.asyncio
async def test_explain_skill_path_for_already_required_skill_is_itself(graph_service: SkillGraphService) -> None:
    path = graph_service.explain_skill_path("skill.python", "role.ml_engineer")
    assert path is not None
    assert [step.skill_id for step in path] == ["skill.python"]


@pytest.mark.asyncio
async def test_shortest_prerequisite_path_no_path_returns_none(graph_service: SkillGraphService) -> None:
    # sql_fundamentals and chain_rule are in unrelated parts of the graph.
    result = graph_service.shortest_prerequisite_path("skill.chain_rule", "skill.sql_fundamentals")
    assert result is None


@pytest.mark.asyncio
async def test_resources_targeting_chain_rule(graph_service: SkillGraphService) -> None:
    resources = graph_service.resources_targeting("skill.chain_rule")
    assert "res.khan_diff_calc" in resources


@pytest.mark.asyncio
async def test_misconceptions_for_skill_and_remediation(graph_service: SkillGraphService) -> None:
    miscs = graph_service.misconceptions_for_skill("skill.backpropagation")
    assert "misc.chain_rule_sum" in miscs
    remediation = graph_service.remediation_resources_for_misconception("misc.chain_rule_sum")
    assert "res.khan_diff_calc" in remediation
