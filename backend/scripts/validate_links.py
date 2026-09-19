"""CLI entrypoint: live link-validation sweep over every catalog resource
(design §15.2: "Link validation job: runs before demo and nightly").

    cd backend
    python scripts/validate_links.py

Requires a running, migrated, seeded Postgres (`alembic upgrade head` +
`scripts/seed_catalog.py` first). Issues a HEAD (falling back to GET)
request per resource URL, bounded concurrency, and writes `link_status`/
`last_verified_at` back via `CatalogRepository.update_link_statuses`. Safe
to re-run: each run just overwrites the prior check's results.
"""
from __future__ import annotations

import asyncio
import sys

import httpx

from app.db.session import SessionLocal
from app.repositories.catalog_repository import CatalogRepository
from app.retrieval.link_validator import validate_resources


async def main() -> None:
    async with SessionLocal() as session:
        catalog = CatalogRepository(session)
        resources = await catalog.get_all_resources()
        pairs = [(r.resource_id, r.url) for r in resources]

        async with httpx.AsyncClient() as client:
            results = await validate_resources(pairs, client)

        updates = {r.resource_id: (r.status, r.checked_at) for r in results}
        updated = await catalog.update_link_statuses(updates)
        await session.commit()

    counts: dict[str, int] = {}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
    print(f"Checked {len(results)} resources, updated {updated}: {counts}")
    broken = [r for r in results if r.status == "broken"]
    if broken:
        print("Broken:", file=sys.stderr)
        for r in broken:
            print(f"  {r.resource_id}: {r.url} ({r.detail})", file=sys.stderr)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:  # noqa: BLE001 - CLI top-level error reporting
        print(f"Link validation failed: {exc}", file=sys.stderr)
        sys.exit(1)
