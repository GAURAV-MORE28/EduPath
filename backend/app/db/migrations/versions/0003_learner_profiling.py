"""learner profiling: learner_profiles, documents, evidence,
learner_skill_states, pending_claims

Revision ID: 0003_learner_profiling
Revises: 0002_skill_graph_catalog
Create Date: 2026-09-19

Adds the learner-overlay tables for Learner Profiling + the Evidence Pipeline
(design §10, §12, §22, §28; ARCHITECTURE_CONTRACTS.md §3). `pending_claims`
is an addition beyond design §28's table list — see
`backend/app/db/models.py`'s `PendingClaim` docstring and
`docs/ARCHITECTURE_CONTRACTS.md`'s Contract Changes for this phase.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_learner_profiling"
down_revision: Union[str, None] = "0002_skill_graph_catalog"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "learner_profiles",
        sa.Column("learner_id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.user_id"), nullable=False, unique=True),
        sa.Column("target_role_id", sa.String(length=128), sa.ForeignKey("roles.role_id"), nullable=False),
        sa.Column("career_goal", sa.Text(), nullable=False, server_default=""),
        sa.Column("experience_summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("weekly_hours", sa.Float(), nullable=False),
        sa.Column("preferences", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("constraints", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "documents",
        sa.Column("document_id", sa.String(length=36), primary_key=True),
        sa.Column(
            "learner_id", sa.String(length=36), sa.ForeignKey("learner_profiles.learner_id"), nullable=False
        ),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("storage_ref", sa.String(length=1024), nullable=False),
        sa.Column("text_hash", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("parse_status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_documents_learner_id", "documents", ["learner_id"])

    op.create_table(
        "evidence",
        sa.Column("evidence_id", sa.String(length=36), primary_key=True),
        sa.Column(
            "learner_id", sa.String(length=36), sa.ForeignKey("learner_profiles.learner_id"), nullable=False
        ),
        sa.Column("skill_id", sa.String(length=128), sa.ForeignKey("skills.skill_id"), nullable=False),
        sa.Column("tier", sa.String(length=4), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("document_id", sa.String(length=36), sa.ForeignKey("documents.document_id"), nullable=True),
        sa.Column("span_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("span_offsets", sa.JSON(), nullable=True),
        sa.Column("assessment_id", sa.String(length=36), nullable=True),
        sa.Column("extracted_by_run", sa.String(length=36), nullable=True),
        sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_evidence_learner_id", "evidence", ["learner_id"])
    op.create_index("ix_evidence_skill_id", "evidence", ["skill_id"])

    op.create_table(
        "learner_skill_states",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "learner_id", sa.String(length=36), sa.ForeignKey("learner_profiles.learner_id"), nullable=False
        ),
        sa.Column("skill_id", sa.String(length=128), sa.ForeignKey("skills.skill_id"), nullable=False),
        sa.Column("alpha", sa.Float(), nullable=False),
        sa.Column("beta", sa.Float(), nullable=False),
        sa.Column("band", sa.String(length=16), nullable=False),
        sa.Column("confidence", sa.String(length=8), nullable=False),
        sa.Column("n_obs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tier_max", sa.String(length=4), nullable=False),
        sa.Column("last_assessed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("learner_id", "skill_id", name="uq_learner_skill_state"),
    )
    op.create_index("ix_learner_skill_states_learner_id", "learner_skill_states", ["learner_id"])
    op.create_index("ix_learner_skill_states_skill_id", "learner_skill_states", ["skill_id"])

    op.create_table(
        "pending_claims",
        sa.Column("claim_id", sa.String(length=36), primary_key=True),
        sa.Column(
            "learner_id", sa.String(length=36), sa.ForeignKey("learner_profiles.learner_id"), nullable=False
        ),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), sa.ForeignKey("documents.document_id"), nullable=True),
        sa.Column("skill_label", sa.String(length=256), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("context_type", sa.String(length=32), nullable=False),
        sa.Column("claimed_level_cue", sa.String(length=128), nullable=True),
        sa.Column("verbatim_span", sa.Text(), nullable=False),
        sa.Column("span_offsets", sa.JSON(), nullable=False),
        sa.Column("tier", sa.String(length=4), nullable=False),
        sa.Column("normalized_skill_id", sa.String(length=128), sa.ForeignKey("skills.skill_id"), nullable=True),
        sa.Column("normalization_method", sa.String(length=24), nullable=False),
        sa.Column("normalization_confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_pending_claims_learner_id", "pending_claims", ["learner_id"])
    op.create_index("ix_pending_claims_run_id", "pending_claims", ["run_id"])


def downgrade() -> None:
    op.drop_table("pending_claims")
    op.drop_table("learner_skill_states")
    op.drop_table("evidence")
    op.drop_table("documents")
    op.drop_table("learner_profiles")
