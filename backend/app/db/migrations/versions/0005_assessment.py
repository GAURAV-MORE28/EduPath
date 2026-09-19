"""assessment: practice_sessions, assessments, struggle_signals,
learner_misconceptions

Revision ID: 0005_assessment
Revises: 0004_planner
Create Date: 2026-09-19

Adds the Assessment/Mastery/Struggle-Detection tables (design §18, §19,
§28; ARCHITECTURE_CONTRACTS.md §17). `practice_sessions` is an addition
beyond design §28's table list -- see `backend/app/db/models.py`'s
`PracticeSession` docstring.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_assessment"
down_revision: Union[str, None] = "0004_planner"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "practice_sessions",
        sa.Column("set_id", sa.String(length=36), primary_key=True),
        sa.Column(
            "learner_id", sa.String(length=36), sa.ForeignKey("learner_profiles.learner_id"), nullable=False
        ),
        sa.Column("skill_id", sa.String(length=128), sa.ForeignKey("skills.skill_id"), nullable=False),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("item_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("misconception_id", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_practice_sessions_learner_id", "practice_sessions", ["learner_id"])
    op.create_index("ix_practice_sessions_skill_id", "practice_sessions", ["skill_id"])

    op.create_table(
        "assessments",
        sa.Column("assessment_id", sa.String(length=36), primary_key=True),
        sa.Column(
            "learner_id", sa.String(length=36), sa.ForeignKey("learner_profiles.learner_id"), nullable=False
        ),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("skill_id", sa.String(length=128), sa.ForeignKey("skills.skill_id"), nullable=False),
        sa.Column("items", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("prereq_block_score", sa.Float(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_assessments_learner_id", "assessments", ["learner_id"])
    op.create_index("ix_assessments_skill_id", "assessments", ["skill_id"])

    op.create_table(
        "struggle_signals",
        sa.Column("signal_id", sa.String(length=36), primary_key=True),
        sa.Column(
            "learner_id", sa.String(length=36), sa.ForeignKey("learner_profiles.learner_id"), nullable=False
        ),
        sa.Column("signal_class", sa.String(length=32), nullable=False),
        sa.Column("skill_id", sa.String(length=128), sa.ForeignKey("skills.skill_id"), nullable=False),
        sa.Column("confidence", sa.String(length=8), nullable=False),
        sa.Column("evidence_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("counts", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("thresholds_used", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(length=8), nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_struggle_signals_learner_id", "struggle_signals", ["learner_id"])
    op.create_index("ix_struggle_signals_skill_id", "struggle_signals", ["skill_id"])

    op.create_table(
        "learner_misconceptions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "learner_id", sa.String(length=36), sa.ForeignKey("learner_profiles.learner_id"), nullable=False
        ),
        sa.Column(
            "misconception_id",
            sa.String(length=128),
            sa.ForeignKey("misconceptions.misconception_id"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("evidence_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("remediation_cycles", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("first_seen", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_remediated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("learner_id", "misconception_id", name="uq_learner_misconception"),
    )
    op.create_index("ix_learner_misconceptions_learner_id", "learner_misconceptions", ["learner_id"])
    op.create_index("ix_learner_misconceptions_misconception_id", "learner_misconceptions", ["misconception_id"])


def downgrade() -> None:
    op.drop_table("learner_misconceptions")
    op.drop_table("struggle_signals")
    op.drop_table("assessments")
    op.drop_table("practice_sessions")
