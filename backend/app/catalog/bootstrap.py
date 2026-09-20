"""Seed the catalog on first start (Phase 12 deployment fix).

`docker compose up` previously produced an API whose catalog tables were empty
(nothing ever ran `seed_catalog.py`), so intake failed with "role not supported".
This seeds the curated domain pack exactly once -- only when the catalog is
empty -- and never re-ingests over a populated database (`replace_all` would
violate learner-scoped foreign keys; see IMPLEMENTATION_STATE.md Known Issues).
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.ingest import IngestionResult, run_ingestion
from app.db.models import Skill
from app.logging_config import get_logger

logger = get_logger(__name__)


async def ensure_catalog(session: AsyncSession) -> IngestionResult | None:
    """Ingest the domain pack iff there are no skills yet. Returns the result, or None
    when the catalog was already populated."""
    existing = (await session.execute(select(func.count()).select_from(Skill))).scalar_one()
    if existing:
        return None
    result = await run_ingestion(session)
    logger.info(
        "edupath.startup.catalog_seeded", graph_version=result.graph_version, skills=result.skill_count,
        resources=result.resource_count, items=result.item_count,
    )
    return result
