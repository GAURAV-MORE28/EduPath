"""reflection: reflection_records, decision_records

Revision ID: 0006_reflection
Revises: 0005_assessment
Create Date: 2026-09-20

Adds the Reflection & Re-planning tables (design §20, §21, §28;
ARCHITECTURE_CONTRACTS.md). See `backend/app/db/models.py`'s
`ReflectionRecord`/`DecisionRecord` docstrings.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006_reflection"
down_revision: Union[str, None] = "0005_assessment"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "reflection_records",
        sa.Column("reflection_id", sa.String(length=36), primary_key=True),
        sa.Column(
            "learner_id", sa.String(length=36), sa.ForeignKey("learner_profiles.learner_id"), nullable=False
        ),
        sa.Column("signal_id", sa.String(length=36), sa.ForeignKey("struggle_signals.signal_id"), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("validated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("rounds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("degraded", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("plan_revision_id", sa.String(length=36), sa.ForeignKey("plan_revisions.revision_id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_reflection_records_learner_id", "reflection_records", ["learner_id"])
    op.create_index("ix_reflection_records_signal_id", "reflection_records", ["signal_id"])

    op.create_table(
        "decision_records",
        sa.Column("decision_id", sa.String(length=36), primary_key=True),
        sa.Column(
            "learner_id", sa.String(length=36), sa.ForeignKey("learner_profiles.learner_id"), nullable=False
        ),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("inputs", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("evidence_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("graph_paths", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("rules_fired", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("scores", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("llm_run_id", sa.String(length=36), nullable=True),
        sa.Column("graph_version", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("output_ref", sa.String(length=36), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_decision_records_learner_id", "decision_records", ["learner_id"])


def downgrade() -> None:
    op.drop_table("decision_records")
    op.drop_table("reflection_records")
