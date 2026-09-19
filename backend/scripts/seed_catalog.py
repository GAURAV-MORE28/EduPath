"""CLI entrypoint: load `data/dataset/*.json` into the configured Postgres
database (`DATABASE_URL` / `.env`, see app/config.py).

    cd backend
    python scripts/seed_catalog.py

Requires a running, migrated Postgres (`alembic upgrade head` first — see
app/db/migrations/versions/0002_skill_graph_catalog.py). Safe to re-run: each
run replaces the entire catalog in one transaction
(CatalogRepository.replace_all) and records a new GraphMeta row.
"""
from __future__ import annotations

import asyncio
import sys

from app.catalog.ingest import run_ingestion
from app.db.session import SessionLocal


async def main() -> None:
    async with SessionLocal() as session:
        result = await run_ingestion(session)
    print(
        f"Ingested graph_version={result.graph_version}: "
        f"{result.skill_count} skills, {result.role_count} roles, {result.edge_count} skill edges, "
        f"{result.resource_count} resources, {result.misconception_count} misconceptions, "
        f"{result.item_count} practice items."
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:  # noqa: BLE001 - CLI top-level error reporting
        print(f"Catalog ingestion failed: {exc}", file=sys.stderr)
        sys.exit(1)
