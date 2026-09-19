"""ORM models.

Phase 1 added only what was needed to prove the migration framework and
session-boundary work (design §28: `User`). Phase 3 (this file, remaining
classes below) adds the curated Skill Graph / catalog tables from
ARCHITECTURE_CONTRACTS.md §5/§9 and design §11.2-§11.3/§15.1/§28: `Skill`,
`SkillEdge`, `Role`, `RoleRequirement`, `Misconception`, `Resource`,
`ResourceSkill`, `PracticeItem`, plus `GraphMeta` (graph-versioning history —
not in design §28's conceptual list, but required by ARCHITECTURE_CONTRACTS.md
§5's "graph is versioned" and §14's "record graph_version in every
DecisionRecord"; see docs/ARCHITECTURE_CONTRACTS.md Contract Changes).

List-valued columns (`aliases`, `remediation_candidates`,
`prerequisite_skill_ids`, `options`) use the generic `JSON` type (as Phase 1
did for `consent_flags`) rather than `postgresql.ARRAY`/`JSONB`, so the same
model works against both Postgres (prod) and SQLite (tests) — the project's
existing dialect-portability convention (see `tests/conftest.py`).
Every other table in the conceptual schema not yet needed
(`LearnerProfile`, `Document`, `Evidence`, ...) is added by the phase that
owns it.
"""
import uuid
from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# Embedding dimensionality for the (currently degraded/deterministic)
# EmbeddingGateway — see app/gateway/embedding_gateway.py. Kept in one place
# per ARCHITECTURE_CONTRACTS.md §14 ("tunable defaults... kept in one place").
EMBEDDING_DIM = 256


class User(Base):
    __tablename__ = "users"

    user_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    consent_flags: Mapped[dict] = mapped_column(JSON, default=dict)


# ---------------------------------------------------------------------------
# Phase 3 — Skill Graph + Catalog (design §11.2-§11.3, §15.1, §28)
# ---------------------------------------------------------------------------


class Skill(Base):
    """Node type `Skill` (design §11.2). Curated, read-mostly."""

    __tablename__ = "skills"

    skill_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    label: Mapped[str] = mapped_column(String(256))
    kind: Mapped[str] = mapped_column(String(32))  # concept / tool / practice
    area: Mapped[str] = mapped_column(String(64))
    aliases: Mapped[list] = mapped_column(JSON, default=list)
    description: Mapped[str] = mapped_column(Text, default="")
    assessable: Mapped[bool] = mapped_column(Boolean, default=True)
    # Skill embeddings are not populated this phase (task scope is resource
    # embeddings only); the column exists so the Skill node matches design
    # §11.2's `embedding vector` property without another migration later.
    embedding: Mapped[list | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SkillEdge(Base):
    """Edge types `PREREQUISITE_OF` / `PART_OF` / `RELATED_TO` (design §11.3).

    The other six closed-set edge types (`REQUIRES`, `TARGETS`, `ASSESSES`,
    `MISCONCEPTION_OF`, `ROOTED_IN`, `REMEDIATED_BY`) are cross-node-type
    relationships and live on the tables that already carry both endpoints
    (`RoleRequirement`, `ResourceSkill`, `PracticeItem.skill_id`,
    `Misconception.skill_id`/`root_skill_id`/`remediation_candidates`) rather
    than duplicated here — see app/graph/loader.py, which materializes all
    nine edge types as NetworkX edges regardless of which table they live in.
    """

    __tablename__ = "skill_edges"
    __table_args__ = (UniqueConstraint("from_skill", "to_skill", "type", name="uq_skill_edge"),)

    edge_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    from_skill: Mapped[str] = mapped_column(String(128), ForeignKey("skills.skill_id"), index=True)
    to_skill: Mapped[str] = mapped_column(String(128), ForeignKey("skills.skill_id"), index=True)
    type: Mapped[str] = mapped_column(String(32))  # PREREQUISITE_OF / PART_OF / RELATED_TO
    strength: Mapped[str | None] = mapped_column(String(8), nullable=True)  # hard / soft (PREREQUISITE_OF only)
    min_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    weight: Mapped[float | None] = mapped_column(Float, nullable=True)  # RELATED_TO only
    source: Mapped[str] = mapped_column(String(32))  # curated / llm_draft_reviewed / imported_candidate
    reviewed_by: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Role(Base):
    """Node type `Role` (design §11.2)."""

    __tablename__ = "roles"

    role_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    title: Mapped[str] = mapped_column(String(256))
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RoleRequirement(Base):
    """Edge type `REQUIRES` (Role → Skill, design §11.3)."""

    __tablename__ = "role_requirements"
    __table_args__ = (UniqueConstraint("role_id", "skill_id", name="uq_role_requirement"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    role_id: Mapped[str] = mapped_column(String(128), ForeignKey("roles.role_id"), index=True)
    skill_id: Mapped[str] = mapped_column(String(128), ForeignKey("skills.skill_id"), index=True)
    required_level: Mapped[int] = mapped_column(Integer)  # 1-3
    weight: Mapped[int] = mapped_column(Integer)  # core 3 / important 2 / nice 1


class Misconception(Base):
    """Node type `Misconception` (design §11.2). Field names follow design
    §28's conceptual schema (`skill_id`, `root_skill_id`, `signature`) rather
    than the domain-pack JSON's (`affected_skill`, `root_prerequisite`,
    `manifestation`); the ingestion loader (app/catalog/ingest.py) does that
    rename. `remediation_candidates` is an addition beyond §28's field list —
    it is what makes the `REMEDIATED_BY` edge type (Misconception → Resource,
    design §11.3) materializable; see Contract Changes.
    """

    __tablename__ = "misconceptions"

    misconception_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    description: Mapped[str] = mapped_column(Text, default="")
    skill_id: Mapped[str] = mapped_column(String(128), ForeignKey("skills.skill_id"), index=True)  # MISCONCEPTION_OF
    root_skill_id: Mapped[str] = mapped_column(String(128), ForeignKey("skills.skill_id"), index=True)  # ROOTED_IN
    signature: Mapped[str] = mapped_column(Text, default="")
    severity: Mapped[str] = mapped_column(String(16))
    remediation_candidates: Mapped[list] = mapped_column(JSON, default=list)  # REMEDIATED_BY -> Resource ids
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Resource(Base):
    """Node type `Resource` (design §11.2, §15.1)."""

    __tablename__ = "resources"

    resource_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    title: Mapped[str] = mapped_column(String(256))
    url: Mapped[str] = mapped_column(String(1024))
    provider: Mapped[str] = mapped_column(String(128))
    type: Mapped[str] = mapped_column(String(32))  # video / article / docs / course / exercise / project / book_chapter
    difficulty: Mapped[int] = mapped_column(Integer)  # 1-3
    duration_min: Mapped[int] = mapped_column(Integer)
    modality: Mapped[str] = mapped_column(String(16))  # watch / read / do
    prerequisite_skill_ids: Mapped[list] = mapped_column(JSON, default=list)
    learning_objective_text: Mapped[str] = mapped_column(Text, default="")
    audience: Mapped[str] = mapped_column(String(32))
    language: Mapped[str] = mapped_column(String(16))
    cost: Mapped[str] = mapped_column(String(16))
    curation_tier: Mapped[str] = mapped_column(String(16))  # curated / community / unvetted
    reviewed_by: Mapped[str] = mapped_column(String(128))
    last_verified_at: Mapped[date | None] = mapped_column(nullable=True)
    link_status: Mapped[str] = mapped_column(String(16))  # ok / redirected / broken
    embedding: Mapped[list | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ResourceSkill(Base):
    """Edge type `TARGETS` (Resource → Skill, design §11.3)."""

    __tablename__ = "resource_skills"
    __table_args__ = (UniqueConstraint("resource_id", "skill_id", name="uq_resource_skill"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    resource_id: Mapped[str] = mapped_column(String(128), ForeignKey("resources.resource_id"), index=True)
    skill_id: Mapped[str] = mapped_column(String(128), ForeignKey("skills.skill_id"), index=True)
    level_from: Mapped[int] = mapped_column(Integer)
    level_to: Mapped[int] = mapped_column(Integer)


class PracticeItem(Base):
    """Node type `PracticeItem` (design §11.2). `purpose`, `explanation`,
    `generated_by`, `validated_by`, `graph_version` are additions beyond
    design §28's field list, carried over verbatim from the domain-pack JSON
    to preserve source/review metadata (see Contract Changes).
    """

    __tablename__ = "practice_items"

    item_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    skill_id: Mapped[str] = mapped_column(String(128), ForeignKey("skills.skill_id"), index=True)  # ASSESSES
    type: Mapped[str] = mapped_column(String(16), default="mcq")
    difficulty: Mapped[str] = mapped_column(String(16))  # easy / medium / hard
    purpose: Mapped[str] = mapped_column(String(32), default="practice")  # practice / probe / resolution-check / ...
    stem: Mapped[str] = mapped_column(Text)
    options: Mapped[list] = mapped_column(JSON, default=list)  # [{text, is_key, misconception_id}]
    explanation: Mapped[str] = mapped_column(Text, default="")
    validated: Mapped[bool] = mapped_column(Boolean, default=False)
    generated_by: Mapped[str] = mapped_column(String(64), default="")
    validated_by: Mapped[str] = mapped_column(String(128), default="")
    graph_version: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GraphMeta(Base):
    """Graph-versioning history (ARCHITECTURE_CONTRACTS.md §5: "Graph is
    curated offline, versioned... graph_version"). One row per successful
    catalog ingestion run — an append-only audit trail, not a singleton, so
    "which graph_version was active when" is answerable later.
    """

    __tablename__ = "graph_meta"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    graph_version: Mapped[str] = mapped_column(String(64), index=True)
    loaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    source: Mapped[str] = mapped_column(String(512))  # e.g. path to data/dataset/
    skill_count: Mapped[int] = mapped_column(Integer)
    role_count: Mapped[int] = mapped_column(Integer)
    edge_count: Mapped[int] = mapped_column(Integer)
    resource_count: Mapped[int] = mapped_column(Integer)
    misconception_count: Mapped[int] = mapped_column(Integer)
    item_count: Mapped[int] = mapped_column(Integer)
