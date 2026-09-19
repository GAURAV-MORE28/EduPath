"""planner: weekly_plans, plan_revisions, plan_items

Revision ID: 0004_planner
Revises: 0003_learner_profiling
Create Date: 2026-09-19

Adds the Planner's persisted tables (design §16, §28; ARCHITECTURE_CONTRACTS.md
§10). `plan_revisions` is created before `plan_items` since
`PlanItem.revision_id` FK-references it (design §28: every item is scoped to
the revision it belongs to).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_planner"
down_revision: Union[str, None] = "0003_learner_profiling"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "weekly_plans",
        sa.Column("plan_id", sa.String(length=36), primary_key=True),
        sa.Column(
            "learner_id", sa.String(length=36), sa.ForeignKey("learner_profiles.learner_id"), nullable=False
        ),
        sa.Column("week_index", sa.Integer(), nullable=False),
        sa.Column("hours_budget", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="draft"),
        sa.Column("current_revision_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_weekly_plans_learner_id", "weekly_plans", ["learner_id"])

    op.create_table(
        "plan_revisions",
        sa.Column("revision_id", sa.String(length=36), primary_key=True),
        sa.Column("plan_id", sa.String(length=36), sa.ForeignKey("weekly_plans.plan_id"), nullable=False),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("parent_revision_id", sa.String(length=36), nullable=True),
        sa.Column("cause_type", sa.String(length=24), nullable=False),
        sa.Column("cause_ref", sa.String(length=256), nullable=False, server_default=""),
        sa.Column("operators", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("diff", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("degraded", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("overall_reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("reverted_by", sa.String(length=36), nullable=True),
    )
    op.create_index("ix_plan_revisions_plan_id", "plan_revisions", ["plan_id"])

    op.create_table(
        "plan_items",
        sa.Column("item_id", sa.String(length=36), primary_key=True),
        sa.Column("plan_id", sa.String(length=36), sa.ForeignKey("weekly_plans.plan_id"), nullable=False),
        sa.Column(
            "revision_id", sa.String(length=36), sa.ForeignKey("plan_revisions.revision_id"), nullable=False
        ),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("objective_id", sa.String(length=256), nullable=False),
        sa.Column("skill_id", sa.String(length=128), sa.ForeignKey("skills.skill_id"), nullable=False),
        sa.Column("resource_id", sa.String(length=128), sa.ForeignKey("resources.resource_id"), nullable=True),
        sa.Column("practice_item_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("est_minutes", sa.Integer(), nullable=False),
        sa.Column("difficulty", sa.Integer(), nullable=False),
        sa.Column("day_slot", sa.Integer(), nullable=False),
        sa.Column("depends_on", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("reason", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="planned"),
    )
    op.create_index("ix_plan_items_plan_id", "plan_items", ["plan_id"])
    op.create_index("ix_plan_items_revision_id", "plan_items", ["revision_id"])
    op.create_index("ix_plan_items_skill_id", "plan_items", ["skill_id"])


def downgrade() -> None:
    op.drop_table("plan_items")
    op.drop_table("plan_revisions")
    op.drop_table("weekly_plans")
