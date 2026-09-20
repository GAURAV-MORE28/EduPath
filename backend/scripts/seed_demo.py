"""Seed / reset the DEMO_MODE persona ("Asha", design §38.1) straight into the database.

    cd backend
    DEMO_MODE=true python scripts/seed_demo.py                 # seed for the dev session user
    DEMO_MODE=true python scripts/seed_demo.py --user my-user  # seed for a specific session cookie value
    DEMO_MODE=true python scripts/seed_demo.py --preflight     # only print the rehearsal checklist

Runs the same code as `POST /api/demo/seed` (intake -> resume ingestion -> claim confirmation -> seeded
evidence state -> week-0 plan), after making sure the catalog is loaded. Idempotent: it resets the persona.
In the browser, the seeded learner is whoever holds the matching `session` cookie ("dev-user" needs none).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys

from app.catalog.bootstrap import ensure_catalog
from app.db.session import SessionLocal
from app.demo.service import preflight, seed_demo_learner
from app.graph.loader import GraphLoader
from app.graph.queries import SkillGraphService
from app.repositories.catalog_repository import CatalogRepository


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--user", default="dev-user", help="session user id to seed (default: the dev fallback user)")
    parser.add_argument("--preflight", action="store_true", help="print the rehearsal checklist and exit")
    args = parser.parse_args()

    async with SessionLocal() as session:
        await ensure_catalog(session)
        graph = SkillGraphService(await GraphLoader(CatalogRepository(session)).load())
        if args.preflight:
            report = await preflight(session, graph)
            print(json.dumps(report, indent=2))
            return 0 if report["ready"] else 1
        result = await seed_demo_learner(session, graph, user_id=args.user)
        print(
            f"Seeded {result.learner_id} for user {result.user_id}: {result.claims_confirmed} claims confirmed "
            f"({result.claims_extracted} extracted), {len(result.seeded_skills)} skills seeded, "
            f"week-0 plan {result.plan_id} with {result.plan_item_count} items."
        )
        report = await preflight(session, graph)
        print("preflight:", "READY" if report["ready"] else "NOT READY", *[f"\n  {'ok ' if c['ok'] else 'FAIL'} {c['name']}: {c['detail']}" for c in report["checks"]])
        return 0 if report["ready"] else 1


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except Exception as exc:  # noqa: BLE001 - CLI top-level error reporting
        print(f"Demo seeding failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
