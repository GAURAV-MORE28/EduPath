"""skill graph + catalog: skills, skill_edges, roles, role_requirements,
misconceptions, resources, resource_skills, practice_items, graph_meta

Revision ID: 0002_skill_graph_catalog
Revises: 0001_foundation
Create Date: 2026-09-19

Adds the Phase 3 tables (design §11.2-§11.3, §15.1, §28;
ARCHITECTURE_CONTRACTS.md §5/§9) and the retrieval-preparation infrastructure
design §14.1/§34 call for: a pgvector column on `resources.embedding`
(vector store already enabled by 0001_foundation's `CREATE EXTENSION vector`)
and a PostgreSQL full-text-search index over `resources.title` +
`resources.learning_objective_text`, generated via `tsvector` so it stays in
sync automatically (Postgres >= 12's `GENERATED ALWAYS AS ... STORED`).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "0002_skill_graph_catalog"
down_revision: Union[str, None] = "0001_foundation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EMBEDDING_DIM = 256


def upgrade() -> None:
    op.create_table(
        "skills",
        sa.Column("skill_id", sa.String(length=128), primary_key=True),
        sa.Column("label", sa.String(length=256), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("area", sa.String(length=64), nullable=False),
        sa.Column("aliases", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("assessable", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "roles",
        sa.Column("role_id", sa.String(length=128), primary_key=True),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "resources",
        sa.Column("resource_id", sa.String(length=128), primary_key=True),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("url", sa.String(length=1024), nullable=False),
        sa.Column("provider", sa.String(length=128), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("difficulty", sa.Integer(), nullable=False),
        sa.Column("duration_min", sa.Integer(), nullable=False),
        sa.Column("modality", sa.String(length=16), nullable=False),
        sa.Column("prerequisite_skill_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("learning_objective_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("audience", sa.String(length=32), nullable=False),
        sa.Column("language", sa.String(length=16), nullable=False),
        sa.Column("cost", sa.String(length=16), nullable=False),
        sa.Column("curation_tier", sa.String(length=16), nullable=False),
        sa.Column("reviewed_by", sa.String(length=128), nullable=False),
        sa.Column("last_verified_at", sa.Date(), nullable=True),
        sa.Column("link_status", sa.String(length=16), nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "skill_edges",
        sa.Column("edge_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("from_skill", sa.String(length=128), sa.ForeignKey("skills.skill_id"), nullable=False),
        sa.Column("to_skill", sa.String(length=128), sa.ForeignKey("skills.skill_id"), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("strength", sa.String(length=8), nullable=True),
        sa.Column("min_level", sa.Integer(), nullable=True),
        sa.Column("weight", sa.Float(), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("reviewed_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("from_skill", "to_skill", "type", name="uq_skill_edge"),
    )
    op.create_index("ix_skill_edges_from_skill", "skill_edges", ["from_skill"])
    op.create_index("ix_skill_edges_to_skill", "skill_edges", ["to_skill"])

    op.create_table(
        "role_requirements",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("role_id", sa.String(length=128), sa.ForeignKey("roles.role_id"), nullable=False),
        sa.Column("skill_id", sa.String(length=128), sa.ForeignKey("skills.skill_id"), nullable=False),
        sa.Column("required_level", sa.Integer(), nullable=False),
        sa.Column("weight", sa.Integer(), nullable=False),
        sa.UniqueConstraint("role_id", "skill_id", name="uq_role_requirement"),
    )
    op.create_index("ix_role_requirements_role_id", "role_requirements", ["role_id"])
    op.create_index("ix_role_requirements_skill_id", "role_requirements", ["skill_id"])

    op.create_table(
        "misconceptions",
        sa.Column("misconception_id", sa.String(length=128), primary_key=True),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("skill_id", sa.String(length=128), sa.ForeignKey("skills.skill_id"), nullable=False),
        sa.Column("root_skill_id", sa.String(length=128), sa.ForeignKey("skills.skill_id"), nullable=False),
        sa.Column("signature", sa.Text(), nullable=False, server_default=""),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("remediation_candidates", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_misconceptions_skill_id", "misconceptions", ["skill_id"])
    op.create_index("ix_misconceptions_root_skill_id", "misconceptions", ["root_skill_id"])

    op.create_table(
        "resource_skills",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("resource_id", sa.String(length=128), sa.ForeignKey("resources.resource_id"), nullable=False),
        sa.Column("skill_id", sa.String(length=128), sa.ForeignKey("skills.skill_id"), nullable=False),
        sa.Column("level_from", sa.Integer(), nullable=False),
        sa.Column("level_to", sa.Integer(), nullable=False),
        sa.UniqueConstraint("resource_id", "skill_id", name="uq_resource_skill"),
    )
    op.create_index("ix_resource_skills_resource_id", "resource_skills", ["resource_id"])
    op.create_index("ix_resource_skills_skill_id", "resource_skills", ["skill_id"])

    op.create_table(
        "practice_items",
        sa.Column("item_id", sa.String(length=128), primary_key=True),
        sa.Column("skill_id", sa.String(length=128), sa.ForeignKey("skills.skill_id"), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False, server_default="mcq"),
        sa.Column("difficulty", sa.String(length=16), nullable=False),
        sa.Column("purpose", sa.String(length=32), nullable=False, server_default="practice"),
        sa.Column("stem", sa.Text(), nullable=False),
        sa.Column("options", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("explanation", sa.Text(), nullable=False, server_default=""),
        sa.Column("validated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("generated_by", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("validated_by", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("graph_version", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_practice_items_skill_id", "practice_items", ["skill_id"])

    op.create_table(
        "graph_meta",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("graph_version", sa.String(length=64), nullable=False),
        sa.Column("loaded_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("source", sa.String(length=512), nullable=False),
        sa.Column("skill_count", sa.Integer(), nullable=False),
        sa.Column("role_count", sa.Integer(), nullable=False),
        sa.Column("edge_count", sa.Integer(), nullable=False),
        sa.Column("resource_count", sa.Integer(), nullable=False),
        sa.Column("misconception_count", sa.Integer(), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False),
    )
    op.create_index("ix_graph_meta_graph_version", "graph_meta", ["graph_version"])

    # PostgreSQL FTS (design §14.1/§34: "PostgreSQL FTS" as the keyword-search
    # plane, kept separate from the pgvector dense-retrieval plane). A
    # generated column stays in sync automatically; GIN makes it queryable.
    op.execute(
        """
        ALTER TABLE resources
        ADD COLUMN search_vector tsvector
        GENERATED ALWAYS AS (
            setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
            setweight(to_tsvector('english', coalesce(learning_objective_text, '')), 'B')
        ) STORED
        """
    )
    op.execute("CREATE INDEX ix_resources_search_vector ON resources USING GIN (search_vector)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_resources_search_vector")
    op.execute("ALTER TABLE resources DROP COLUMN IF EXISTS search_vector")
    op.drop_table("graph_meta")
    op.drop_table("practice_items")
    op.drop_table("resource_skills")
    op.drop_table("misconceptions")
    op.drop_table("role_requirements")
    op.drop_table("skill_edges")
    op.drop_table("resources")
    op.drop_table("roles")
    op.drop_table("skills")
