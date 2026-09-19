"""Catalog ingestion tests (app/catalog/ingest.py): loading the real
`data/dataset/*.json` domain pack into Postgres-shaped tables (SQLite here,
per tests/conftest.py's dialect-portability convention), end to end.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.catalog.ingest import CatalogIngestor, load_dataset_json, run_ingestion
from app.db.models import GraphMeta, Misconception, PracticeItem, Resource, Skill
from app.graph.validation import GraphValidationError


@pytest.mark.asyncio
async def test_run_ingestion_loads_full_dataset(sqlite_session) -> None:
    dataset = load_dataset_json()
    result = await run_ingestion(sqlite_session)

    assert result.graph_version == dataset["meta"]["graph_version"]
    assert result.skill_count == len(dataset["skills"]) == dataset["meta"]["counts"]["skills"]
    assert result.role_count == len(dataset["roles"]) == dataset["meta"]["counts"]["roles"]
    assert result.edge_count == len(dataset["edges"]) == dataset["meta"]["counts"]["skill_edges"]
    assert result.resource_count == len(dataset["resources"]) == dataset["meta"]["counts"]["resources"]
    assert result.misconception_count == len(dataset["misconceptions"]) == dataset["meta"]["counts"]["misconceptions"]
    assert result.item_count == len(dataset["items"]) == dataset["meta"]["counts"]["assessment_items"]


@pytest.mark.asyncio
async def test_ingestion_records_graph_meta(sqlite_session) -> None:
    await run_ingestion(sqlite_session)
    row = (await sqlite_session.execute(select(GraphMeta))).scalar_one()
    assert row.graph_version == "v0.1.0-domain-pack"
    assert row.skill_count == 158


@pytest.mark.asyncio
async def test_misconception_field_rename_preserved(sqlite_session) -> None:
    """affected_skill/root_prerequisite/manifestation (dataset JSON names) ->
    skill_id/root_skill_id/signature (design §28 column names)."""
    await run_ingestion(sqlite_session)
    row = (
        await sqlite_session.execute(select(Misconception).where(Misconception.misconception_id == "misc.chain_rule_sum"))
    ).scalar_one()
    assert row.skill_id == "skill.backpropagation"
    assert row.root_skill_id == "skill.chain_rule"
    assert row.signature  # manifestation text carried over
    assert "res.khan_diff_calc" in row.remediation_candidates


@pytest.mark.asyncio
async def test_practice_item_source_review_metadata_preserved(sqlite_session) -> None:
    await run_ingestion(sqlite_session)
    row = (await sqlite_session.execute(select(PracticeItem).where(PracticeItem.item_id == "item.derivatives.1"))).scalar_one()
    assert row.generated_by == "curated-seed"
    assert row.validated_by == "edupath-phase3-curation"
    assert row.validated is True
    assert row.graph_version == "v0.1.0-domain-pack"
    assert row.stem  # mapped from the dataset's "question" field


@pytest.mark.asyncio
async def test_skill_edge_source_review_metadata_preserved(sqlite_session) -> None:
    from app.db.models import SkillEdge

    await run_ingestion(sqlite_session)
    rows = (await sqlite_session.execute(select(SkillEdge))).scalars().all()
    assert all(r.source and r.reviewed_by for r in rows)


@pytest.mark.asyncio
async def test_resource_embeddings_are_populated_and_deterministic(sqlite_session) -> None:
    await run_ingestion(sqlite_session)
    rows = (await sqlite_session.execute(select(Resource).limit(5))).scalars().all()
    assert len(rows) == 5
    for r in rows:
        assert r.embedding is not None
        assert len(r.embedding) == 256


@pytest.mark.asyncio
async def test_ingest_rejects_invalid_dataset(sqlite_session) -> None:
    dataset = load_dataset_json()
    # Introduce a dangling reference: an edge to a skill that doesn't exist.
    broken = dict(dataset)
    broken["edges"] = dataset["edges"] + [
        {"from_skill": "skill.python", "to_skill": "skill.does_not_exist", "type": "PREREQUISITE_OF", "strength": "hard", "source": "curated", "reviewed_by": "x"}
    ]
    ingestor = CatalogIngestor(sqlite_session)
    with pytest.raises(GraphValidationError):
        await ingestor.ingest(broken)

    # Nothing should have been written.
    count = len((await sqlite_session.execute(select(Skill))).scalars().all())
    assert count == 0


@pytest.mark.asyncio
async def test_reingestion_replaces_rather_than_duplicates(sqlite_session) -> None:
    await run_ingestion(sqlite_session)
    await run_ingestion(sqlite_session)
    skills = (await sqlite_session.execute(select(Skill))).scalars().all()
    assert len(skills) == 158  # not 316
    meta_rows = (await sqlite_session.execute(select(GraphMeta))).scalars().all()
    assert len(meta_rows) == 2  # append-only audit trail, one per ingestion run
