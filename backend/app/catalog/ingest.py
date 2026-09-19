"""Catalog ingestion — the one-time (or admin-triggered re-run) loader from
the offline-curated domain-pack JSON (`data/dataset/*.json`, design §11.5)
into Postgres, per ARCHITECTURE_CONTRACTS.md §5 ("Graph is curated offline,
versioned, loaded from Postgres into NetworkX at process startup") and
`data/README.md`'s "Consuming this data" section.

Pipeline: read JSON -> validate (`app/graph/validation.py`, fail fast on any
hard error, nothing partially written) -> map to ORM rows (renaming a few
fields to match design §28's column names — see `app/db/models.py`'s
docstrings) -> compute resource embeddings (`app/gateway/embedding_gateway.py`)
-> `CatalogRepository.replace_all()` in one transaction -> record a
`GraphMeta` row.

Not run automatically at import time or app startup — call `run_ingestion()`
explicitly (see `backend/scripts/seed_catalog.py` for a CLI entrypoint),
matching `data/scripts/build_dataset.py` / `validate_dataset.py`'s existing
"explicit script, not auto-run" pattern.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

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
from app.gateway.embedding_gateway import EmbeddingGateway, get_embedding_gateway
from app.graph.validation import GraphValidationError, GraphValidator
from app.repositories.catalog_repository import CatalogRepository

# backend/app/catalog/ingest.py -> parents[3] == repo root
DEFAULT_DATASET_DIR = Path(__file__).resolve().parents[3] / "data" / "dataset"


@dataclass
class IngestionResult:
    graph_version: str
    skill_count: int
    role_count: int
    edge_count: int
    resource_count: int
    misconception_count: int
    item_count: int


def load_dataset_json(dataset_dir: Path = DEFAULT_DATASET_DIR) -> dict[str, Any]:
    def _load(name: str) -> Any:
        return json.loads((dataset_dir / name).read_text(encoding="utf-8"))

    return {
        "meta": _load("meta.json"),
        "skills": _load("skills.json"),
        "roles": _load("roles.json"),
        "edges": _load("skill_edges.json"),
        "resources": _load("resources.json"),
        "misconceptions": _load("misconceptions.json"),
        "items": _load("assessment_items.json"),
    }


class CatalogIngestor:
    def __init__(self, session: AsyncSession, embedding_gateway: EmbeddingGateway | None = None) -> None:
        self.session = session
        self.repository = CatalogRepository(session)
        self.embedding_gateway = embedding_gateway or get_embedding_gateway()

    async def ingest(self, dataset: dict[str, Any], *, source: str = str(DEFAULT_DATASET_DIR)) -> IngestionResult:
        report = GraphValidator().validate(
            skills=dataset["skills"],
            roles=dataset["roles"],
            edges=dataset["edges"],
            resources=dataset["resources"],
            misconceptions=dataset["misconceptions"],
            items=dataset["items"],
        )
        if not report.ok:
            raise GraphValidationError(report)

        graph_version = dataset["meta"]["graph_version"]

        skills = [self._build_skill(s) for s in dataset["skills"]]
        roles = [self._build_role(r) for r in dataset["roles"]]
        role_requirements = [
            self._build_role_requirement(r["role_id"], rs)
            for r in dataset["roles"]
            for rs in r["required_skills"]
        ]
        skill_edges = [self._build_skill_edge(e) for e in dataset["edges"]]
        misconceptions = [self._build_misconception(m) for m in dataset["misconceptions"]]
        resources = [await self._build_resource(r) for r in dataset["resources"]]
        resource_skills = [
            self._build_resource_skill(r["resource_id"], st)
            for r in dataset["resources"]
            for st in r["skill_targets"]
        ]
        practice_items = [self._build_practice_item(it) for it in dataset["items"]]

        graph_meta = GraphMeta(
            graph_version=graph_version,
            source=source,
            skill_count=len(skills),
            role_count=len(roles),
            edge_count=len(skill_edges),
            resource_count=len(resources),
            misconception_count=len(misconceptions),
            item_count=len(practice_items),
        )

        await self.repository.replace_all(
            skills=skills,
            skill_edges=skill_edges,
            roles=roles,
            role_requirements=role_requirements,
            misconceptions=misconceptions,
            resources=resources,
            resource_skills=resource_skills,
            practice_items=practice_items,
            graph_meta=graph_meta,
        )
        await self.session.commit()

        return IngestionResult(
            graph_version=graph_version,
            skill_count=len(skills),
            role_count=len(roles),
            edge_count=len(skill_edges),
            resource_count=len(resources),
            misconception_count=len(misconceptions),
            item_count=len(practice_items),
        )

    # -- mappers: dataset JSON shape -> ORM rows -----------------------------
    # Field renames follow app/db/models.py's docstrings (design §28 naming
    # where design specifies it; the dataset's own field names otherwise).

    @staticmethod
    def _build_skill(s: dict) -> Skill:
        return Skill(
            skill_id=s["skill_id"],
            label=s["label"],
            kind=s["kind"],
            area=s["category"],
            aliases=s["aliases"],
            description=s["description"],
            assessable=s["assessable"],
        )

    @staticmethod
    def _build_role(r: dict) -> Role:
        return Role(role_id=r["role_id"], title=r["title"], description=r["description"])

    @staticmethod
    def _build_role_requirement(role_id: str, rs: dict) -> RoleRequirement:
        return RoleRequirement(
            role_id=role_id,
            skill_id=rs["skill_id"],
            required_level=rs["required_level"],
            weight=rs["weight"],
        )

    @staticmethod
    def _build_skill_edge(e: dict) -> SkillEdge:
        return SkillEdge(
            from_skill=e["from_skill"],
            to_skill=e["to_skill"],
            type=e["type"],
            strength=e.get("strength"),
            min_level=e.get("min_level"),
            weight=e.get("weight"),
            source=e["source"],
            reviewed_by=e["reviewed_by"],
        )

    @staticmethod
    def _build_misconception(m: dict) -> Misconception:
        return Misconception(
            misconception_id=m["misconception_id"],
            description=m["description"],
            skill_id=m["affected_skill"],
            root_skill_id=m["root_prerequisite"],
            signature=m["manifestation"],
            severity=m["severity"],
            remediation_candidates=m["remediation_candidates"],
        )

    async def _build_resource(self, r: dict) -> Resource:
        embedding_text = f"{r['title']}. {r['learning_objective_text']}"
        embedding = await self.embedding_gateway.embed(embedding_text)
        last_verified_at = date.fromisoformat(r["last_verified_at"]) if r.get("last_verified_at") else None
        return Resource(
            resource_id=r["resource_id"],
            title=r["title"],
            url=r["url"],
            provider=r["provider"],
            type=r["type"],
            difficulty=r["difficulty"],
            duration_min=r["duration_min"],
            modality=r["modality"],
            prerequisite_skill_ids=r["prerequisite_skill_ids"],
            learning_objective_text=r["learning_objective_text"],
            audience=r["audience"],
            language=r["language"],
            cost=r["cost"],
            curation_tier=r["curation_tier"],
            reviewed_by=r["reviewed_by"],
            last_verified_at=last_verified_at,
            link_status=r["link_status"],
            embedding=embedding,
        )

    @staticmethod
    def _build_resource_skill(resource_id: str, st: dict) -> ResourceSkill:
        return ResourceSkill(
            resource_id=resource_id,
            skill_id=st["skill_id"],
            level_from=st["level_from"],
            level_to=st["level_to"],
        )

    @staticmethod
    def _build_practice_item(it: dict) -> PracticeItem:
        return PracticeItem(
            item_id=it["item_id"],
            skill_id=it["skill_id"],
            difficulty=it["difficulty"],
            purpose=it["purpose"],
            stem=it["question"],
            options=it["options"],
            explanation=it["explanation"],
            validated=bool(it.get("validated_by")),
            generated_by=it["generated_by"],
            validated_by=it["validated_by"],
            graph_version=it["graph_version"],
        )


async def run_ingestion(session: AsyncSession, dataset_dir: Path = DEFAULT_DATASET_DIR) -> IngestionResult:
    """Convenience entrypoint: load JSON from `dataset_dir` and ingest it."""
    dataset = load_dataset_json(dataset_dir)
    ingestor = CatalogIngestor(session)
    return await ingestor.ingest(dataset, source=str(dataset_dir))
