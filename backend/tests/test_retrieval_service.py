"""`ResourceRetrievalService` (`app/retrieval/service.py`) and its
`CatalogRepository` support methods, against the real curated dataset via
the `catalog_session` fixture (`tests/conftest.py`) -- same pattern as
`tests/test_graph_queries.py`/`tests/test_gap_engine.py`. The pure ranking
algorithm itself is covered by `tests/test_ranker.py`; this file exercises
the DB-fetch + real `EmbeddingGateway` wiring around it.
"""
from __future__ import annotations

import pytest

from app.gateway.embedding_gateway import DegradedEmbeddingGateway
from app.graph.loader import GraphLoader
from app.graph.queries import SkillGraphService, UnknownSkillError
from app.repositories.catalog_repository import CatalogRepository
from app.retrieval.service import ResourceRetrievalService


@pytest.fixture
async def retrieval_service(catalog_session) -> ResourceRetrievalService:
    catalog = CatalogRepository(catalog_session)
    skill_graph = await GraphLoader(catalog).load()
    graph_service = SkillGraphService(skill_graph)
    return ResourceRetrievalService(catalog, graph_service, DegradedEmbeddingGateway())


@pytest.mark.asyncio
async def test_get_resources_targeting_skill_returns_real_target_edges(catalog_session) -> None:
    catalog = CatalogRepository(catalog_session)
    pairs = await catalog.get_resources_targeting_skill("skill.chain_rule")
    ids = {resource.resource_id for resource, _ in pairs}
    assert "res.khan_diff_calc" in ids
    khan = next((r, rs) for r, rs in pairs if r.resource_id == "res.khan_diff_calc")
    resource, resource_skill = khan
    assert resource_skill.level_from == 0
    assert resource_skill.level_to == 1
    assert resource.curation_tier == "curated"
    assert resource.link_status == "ok"


@pytest.mark.asyncio
async def test_recommend_for_skill_returns_real_resource_ids(retrieval_service: ResourceRetrievalService) -> None:
    recs = await retrieval_service.recommend_for_skill(
        skill_id="skill.chain_rule",
        objective_id="obj.role.ml_engineer.skill.chain_rule",
        current_level=0,
        met_skill_ids={"skill.algebra_basics"},
        session_cap_minutes=400,  # real curated course/video resources here run 190-360 min
        top_k=5,
    )
    assert recs
    assert all(r.skill_id == "skill.chain_rule" for r in recs)
    assert all(r.objective_id == "obj.role.ml_engineer.skill.chain_rule" for r in recs)
    resource_ids = {r.resource_id for r in recs}
    assert resource_ids <= {"res.khan_diff_calc", "res.3b1b_calculus"}


@pytest.mark.asyncio
async def test_recommend_for_skill_empty_when_prerequisite_unmet(retrieval_service: ResourceRetrievalService) -> None:
    # Both res.khan_diff_calc and res.3b1b_calculus require skill.algebra_basics.
    recs = await retrieval_service.recommend_for_skill(
        skill_id="skill.chain_rule", current_level=0, met_skill_ids=set(), session_cap_minutes=400
    )
    assert recs == []


@pytest.mark.asyncio
async def test_recommend_for_skill_empty_when_session_cap_too_small(retrieval_service: ResourceRetrievalService) -> None:
    recs = await retrieval_service.recommend_for_skill(
        skill_id="skill.chain_rule", current_level=0, met_skill_ids={"skill.algebra_basics"}, session_cap_minutes=10
    )
    assert recs == []


@pytest.mark.asyncio
async def test_recommend_for_unknown_skill_raises(retrieval_service: ResourceRetrievalService) -> None:
    with pytest.raises(UnknownSkillError):
        await retrieval_service.recommend_for_skill(skill_id="skill.does_not_exist", current_level=0)


@pytest.mark.asyncio
async def test_recommend_for_skill_with_no_targeting_resources_returns_empty(
    catalog_session, retrieval_service: ResourceRetrievalService
) -> None:
    # Find a real curated skill with zero TARGETS resources (rather than hardcoding a
    # guess against a dataset that can change) -- an empty candidate pool must return
    # an empty list, never raise.
    catalog = CatalogRepository(catalog_session)
    all_skills = {s.skill_id for s in await catalog.get_all_skills()}
    targeted_skills = {rs.skill_id for rs in await catalog.get_all_resource_skills()}
    untargeted = all_skills - targeted_skills
    assert untargeted, "expected at least one skill with no targeting resource in the curated pack"

    recs = await retrieval_service.recommend_for_skill(
        skill_id=next(iter(untargeted)), current_level=0, session_cap_minutes=400, met_skill_ids=set()
    )
    assert recs == []


# -- CatalogRepository.update_link_statuses ------------------------------------


@pytest.mark.asyncio
async def test_update_link_statuses_applies_and_skips_unknown_ids(catalog_session) -> None:
    from datetime import date

    catalog = CatalogRepository(catalog_session)
    checked_at = date(2026, 1, 1)
    updated = await catalog.update_link_statuses(
        {
            "res.khan_diff_calc": ("broken", checked_at),
            "res.does_not_exist": ("ok", checked_at),
        }
    )
    assert updated == 1

    resource = next(r for r in await catalog.get_all_resources() if r.resource_id == "res.khan_diff_calc")
    assert resource.link_status == "broken"
    assert resource.last_verified_at == checked_at


@pytest.mark.asyncio
async def test_update_link_statuses_empty_input_is_a_noop(catalog_session) -> None:
    catalog = CatalogRepository(catalog_session)
    assert await catalog.update_link_statuses({}) == 0
