"""GraphLoader tests (app/graph/loader.py): Postgres-shaped rows -> NetworkX
graph, all nine closed-set edge types materialized (ARCHITECTURE_CONTRACTS.md
§5's node/edge closed sets, design §11.2/§11.3).
"""
from __future__ import annotations

import pytest

from app.graph.loader import (
    NODE_TYPE_MISCONCEPTION,
    NODE_TYPE_PRACTICE_ITEM,
    NODE_TYPE_RESOURCE,
    NODE_TYPE_ROLE,
    NODE_TYPE_SKILL,
    GraphLoader,
)
from app.repositories.catalog_repository import CatalogRepository

CLOSED_EDGE_TYPES = {
    "PREREQUISITE_OF",
    "PART_OF",
    "REQUIRES",
    "TARGETS",
    "ASSESSES",
    "MISCONCEPTION_OF",
    "ROOTED_IN",
    "REMEDIATED_BY",
    "RELATED_TO",
}


@pytest.mark.asyncio
async def test_graph_loads_all_node_types(catalog_session) -> None:
    skill_graph = await GraphLoader(CatalogRepository(catalog_session)).load()
    g = skill_graph.graph

    node_types = {d["node_type"] for _, d in g.nodes(data=True)}
    assert node_types == {
        NODE_TYPE_SKILL,
        NODE_TYPE_ROLE,
        NODE_TYPE_MISCONCEPTION,
        NODE_TYPE_RESOURCE,
        NODE_TYPE_PRACTICE_ITEM,
    }
    assert sum(1 for _, d in g.nodes(data=True) if d["node_type"] == NODE_TYPE_SKILL) == 158
    assert sum(1 for _, d in g.nodes(data=True) if d["node_type"] == NODE_TYPE_ROLE) == 3
    assert sum(1 for _, d in g.nodes(data=True) if d["node_type"] == NODE_TYPE_RESOURCE) == 140


@pytest.mark.asyncio
async def test_graph_materializes_every_closed_set_edge_type(catalog_session) -> None:
    skill_graph = await GraphLoader(CatalogRepository(catalog_session)).load()
    edge_types = {d["type"] for _, _, d in skill_graph.graph.edges(data=True)}
    assert edge_types == CLOSED_EDGE_TYPES


@pytest.mark.asyncio
async def test_related_to_edges_are_bidirectional(catalog_session) -> None:
    skill_graph = await GraphLoader(CatalogRepository(catalog_session)).load()
    g = skill_graph.graph
    # skill.pandas RELATED_TO skill.excel is in the curated pack (weight 0.4)
    forward = [d for d in g.get_edge_data("skill.pandas", "skill.excel", default={}).values() if d.get("type") == "RELATED_TO"]
    backward = [d for d in g.get_edge_data("skill.excel", "skill.pandas", default={}).values() if d.get("type") == "RELATED_TO"]
    assert forward and backward


@pytest.mark.asyncio
async def test_graph_version_matches_ingested_meta(catalog_session) -> None:
    skill_graph = await GraphLoader(CatalogRepository(catalog_session)).load()
    assert skill_graph.graph_version == "v0.1.0-domain-pack"


@pytest.mark.asyncio
async def test_resource_targets_and_misconception_relationships(catalog_session) -> None:
    skill_graph = await GraphLoader(CatalogRepository(catalog_session)).load()
    g = skill_graph.graph

    # TARGETS: resource -> skill
    targets = [(u, v) for u, v, d in g.edges(data=True) if d.get("type") == "TARGETS" and u == "res.khan_diff_calc"]
    assert ("res.khan_diff_calc", "skill.chain_rule") in targets

    # MISCONCEPTION_OF / ROOTED_IN: misconception -> skill
    moc = [(u, v) for u, v, d in g.edges(data=True) if d.get("type") == "MISCONCEPTION_OF" and u == "misc.chain_rule_sum"]
    assert moc == [("misc.chain_rule_sum", "skill.backpropagation")]
    rooted = [(u, v) for u, v, d in g.edges(data=True) if d.get("type") == "ROOTED_IN" and u == "misc.chain_rule_sum"]
    assert rooted == [("misc.chain_rule_sum", "skill.chain_rule")]

    # REMEDIATED_BY: misconception -> resource
    remediated = {v for u, v, d in g.edges(data=True) if d.get("type") == "REMEDIATED_BY" and u == "misc.chain_rule_sum"}
    assert "res.khan_diff_calc" in remediated

    # ASSESSES: item -> skill
    assesses = [(u, v) for u, v, d in g.edges(data=True) if d.get("type") == "ASSESSES" and u == "item.derivatives.1"]
    assert assesses == [("item.derivatives.1", "skill.derivatives")]

    # REQUIRES: role -> skill
    requires = [v for _, v, d in g.edges(data=True) if d.get("type") == "REQUIRES" and _ == "role.ml_engineer"]
    assert "skill.python" in requires
