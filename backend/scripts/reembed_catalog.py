"""Re-embed the stored catalog with the CURRENT embedding provider.

    cd backend && python scripts/reembed_catalog.py

Catalog vectors (`resources.embedding`) and query vectors must come from the same provider, or dense
retrieval compares two unrelated spaces. Run this after changing `EMBEDDING_PROVIDER` /
`EMBEDDING_MODEL` on a database that is already seeded. (A fresh database is embedded correctly at seed
time.) Touches only the `embedding` column: no learner data, no catalog content, no foreign keys.
"""
from __future__ import annotations

import asyncio
import sys

from sqlalchemy import select

from app.db.models import Resource
from app.db.session import SessionLocal
from app.gateway.embedding_gateway import get_embedding_gateway


async def main() -> int:
    gateway = get_embedding_gateway()
    async with SessionLocal() as session:
        resources = (await session.execute(select(Resource))).scalars().all()
        texts = [f"{r.title}. {r.learning_objective_text}" for r in resources]
        vectors = await gateway.embed_many(texts)
        for resource, vector in zip(resources, vectors):
            resource.embedding = vector
        await session.commit()
    print(f"Re-embedded {len(resources)} resources with {type(gateway).__name__}.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except Exception as exc:  # noqa: BLE001 - CLI top-level error reporting
        print(f"Re-embedding failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
