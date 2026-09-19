"""Catalog repository — the data-access layer for the Phase 3 Skill Graph /
catalog tables (design §28, ARCHITECTURE_CONTRACTS.md §5/§9).

Two responsibilities:
  - Bulk load: `replace_all()` is how `app/catalog/ingest.py` writes a
    validated catalog snapshot into Postgres. The curated graph is authored
    and versioned offline as a whole (design §11.5), not edited row-by-row
    through the app, so a full delete-then-insert per ingestion run is the
    right shape here (simpler and safer than per-row upsert/conflict
    handling across two SQL dialects) rather than an incremental diff.
  - Read: `get_*` / `fetch_all()` are how `app/graph/loader.py` reads the
    catalog back out to build the NetworkX graph, and how later phases (Gap
    Engine, Planner, Resource Retriever) will read it.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    GraphMeta,
    Misconception,
    PracticeItem,
    Resource,
    ResourceSkill,
    Role,
    RoleRequirement,
    Skill,
    SkillEdge,
)


@dataclass
class CatalogSnapshot:
    """Everything `app/graph/loader.py` needs to build a NetworkX graph, and
    everything `app/graph/validation.py` needs to re-check invariants against
    what is actually in the database (as opposed to what was last ingested).
    """

    skills: list[Skill]
    skill_edges: list[SkillEdge]
    roles: list[Role]
    role_requirements: list[RoleRequirement]
    misconceptions: list[Misconception]
    resources: list[Resource]
    resource_skills: list[ResourceSkill]
    practice_items: list[PracticeItem]
    graph_meta: GraphMeta | None


class CatalogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -- bulk write (ingestion) ------------------------------------------

    async def replace_all(
        self,
        *,
        skills: list[Skill],
        skill_edges: list[SkillEdge],
        roles: list[Role],
        role_requirements: list[RoleRequirement],
        misconceptions: list[Misconception],
        resources: list[Resource],
        resource_skills: list[ResourceSkill],
        practice_items: list[PracticeItem],
        graph_meta: GraphMeta,
    ) -> None:
        """Replace the entire curated catalog in one transaction. Deletes in
        dependent-first order (children before the skills/roles/resources
        they reference), then inserts in parent-first order. Does not
        commit — the caller controls the transaction boundary.
        """
        # children first (FK dependents)
        for model in (
            PracticeItem,
            ResourceSkill,
            RoleRequirement,
            SkillEdge,
            Misconception,
        ):
            await self.session.execute(delete(model))
        # then parents
        for model in (Resource, Role, Skill):
            await self.session.execute(delete(model))

        self.session.add_all(skills)
        await self.session.flush()
        self.session.add_all(roles)
        self.session.add_all(resources)
        await self.session.flush()
        self.session.add_all(skill_edges)
        self.session.add_all(role_requirements)
        self.session.add_all(misconceptions)
        self.session.add_all(resource_skills)
        self.session.add_all(practice_items)
        self.session.add(graph_meta)
        await self.session.flush()

    # -- read --------------------------------------------------------------

    async def get_all_skills(self) -> list[Skill]:
        return list((await self.session.execute(select(Skill))).scalars().all())

    async def get_all_skill_edges(self) -> list[SkillEdge]:
        return list((await self.session.execute(select(SkillEdge))).scalars().all())

    async def get_all_roles(self) -> list[Role]:
        return list((await self.session.execute(select(Role))).scalars().all())

    async def get_all_role_requirements(self) -> list[RoleRequirement]:
        return list((await self.session.execute(select(RoleRequirement))).scalars().all())

    async def get_all_misconceptions(self) -> list[Misconception]:
        return list((await self.session.execute(select(Misconception))).scalars().all())

    async def get_all_resources(self) -> list[Resource]:
        return list((await self.session.execute(select(Resource))).scalars().all())

    async def get_all_resource_skills(self) -> list[ResourceSkill]:
        return list((await self.session.execute(select(ResourceSkill))).scalars().all())

    async def get_all_practice_items(self) -> list[PracticeItem]:
        return list((await self.session.execute(select(PracticeItem))).scalars().all())

    async def get_role(self, role_id: str) -> Role | None:
        result = await self.session.execute(select(Role).where(Role.role_id == role_id))
        return result.scalar_one_or_none()

    async def get_resources_targeting_skill(self, skill_id: str) -> list[tuple[Resource, ResourceSkill]]:
        """`(Resource, ResourceSkill)` pairs for every `TARGETS` edge into
        `skill_id` — the Resource Retriever's (Phase 6) raw candidate pool
        before eligibility filtering/ranking (`app/retrieval/`). A plain
        SQL join, dialect-portable (SQLite in tests, Postgres in prod),
        unlike `search_resources_by_text`/`search_resources_by_vector`
        above.
        """
        result = await self.session.execute(
            select(Resource, ResourceSkill)
            .join(ResourceSkill, ResourceSkill.resource_id == Resource.resource_id)
            .where(ResourceSkill.skill_id == skill_id)
        )
        return [(row[0], row[1]) for row in result.all()]

    async def update_link_statuses(self, results: dict[str, tuple[str, date]]) -> int:
        """Bulk-apply a link-validation run's results (design §15.2's "link
        validation job... sets `link_status`"): `results` maps
        `resource_id -> (link_status, last_verified_at)`. Skips unknown
        resource IDs rather than raising (a stale/removed resource in a run
        that started before a re-ingestion shouldn't fail the whole job).
        Returns the number of rows actually updated. Does not commit — the
        caller controls the transaction boundary (`backend/scripts/validate_links.py`).
        """
        if not results:
            return 0
        rows = await self.session.execute(select(Resource).where(Resource.resource_id.in_(results)))
        updated = 0
        for resource in rows.scalars().all():
            status, verified_at = results[resource.resource_id]
            resource.link_status = status
            resource.last_verified_at = verified_at
            updated += 1
        return updated

    async def get_latest_graph_meta(self) -> GraphMeta | None:
        result = await self.session.execute(
            select(GraphMeta).order_by(GraphMeta.loaded_at.desc(), GraphMeta.id.desc()).limit(1)
        )
        return result.scalar_one_or_none()

    async def search_resources_by_text(self, query: str, limit: int = 10) -> list[Resource]:
        """PostgreSQL FTS lookup over `resources.search_vector` (the
        generated `tsvector` column from migration 0002 — design §14.1's
        keyword-retrieval plane, kept separate from pgvector dense
        retrieval). Postgres-only: the generated column doesn't exist under
        the SQLite test dialect, so this raises there rather than silently
        returning nothing.
        """
        if self.session.bind is None or self.session.bind.dialect.name != "postgresql":
            raise NotImplementedError(
                "Full-text search requires PostgreSQL (the generated resources.search_vector column)."
            )
        result = await self.session.execute(
            text(
                "SELECT resource_id FROM resources "
                "WHERE search_vector @@ plainto_tsquery('english', :q) "
                "ORDER BY ts_rank(search_vector, plainto_tsquery('english', :q)) DESC LIMIT :limit"
            ),
            {"q": query, "limit": limit},
        )
        ordered_ids = [row[0] for row in result.all()]
        if not ordered_ids:
            return []
        rows = await self.session.execute(select(Resource).where(Resource.resource_id.in_(ordered_ids)))
        by_id = {r.resource_id: r for r in rows.scalars().all()}
        return [by_id[rid] for rid in ordered_ids if rid in by_id]

    async def search_resources_by_vector(self, embedding: list[float], limit: int = 10) -> list[Resource]:
        """pgvector cosine-distance nearest-neighbor lookup over
        `resources.embedding` (design §14.1's dense-retrieval plane).
        Postgres-only: pgvector's comparator operators (`<=>`) are not valid
        SQLite syntax, so this raises there rather than failing with a raw
        `OperationalError` (the `Vector` column type itself is stored fine
        under SQLite for round-trip tests — see
        app/gateway/embedding_gateway.py — only the distance operator is
        Postgres-specific).
        """
        if self.session.bind is None or self.session.bind.dialect.name != "postgresql":
            raise NotImplementedError("Vector similarity search requires PostgreSQL (pgvector's <=> operator).")
        result = await self.session.execute(
            select(Resource).order_by(Resource.embedding.cosine_distance(embedding)).limit(limit)
        )
        return list(result.scalars().all())

    async def fetch_all(self) -> CatalogSnapshot:
        return CatalogSnapshot(
            skills=await self.get_all_skills(),
            skill_edges=await self.get_all_skill_edges(),
            roles=await self.get_all_roles(),
            role_requirements=await self.get_all_role_requirements(),
            misconceptions=await self.get_all_misconceptions(),
            resources=await self.get_all_resources(),
            resource_skills=await self.get_all_resource_skills(),
            practice_items=await self.get_all_practice_items(),
            graph_meta=await self.get_latest_graph_meta(),
        )
