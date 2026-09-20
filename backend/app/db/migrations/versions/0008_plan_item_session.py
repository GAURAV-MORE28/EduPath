"""plan_items.session: which study session of a resource a plan item is

Revision ID: 0008_plan_item_session
Revises: 0007_observability
Create Date: 2026-09-20

Stage 2 (resource sessionization, `docs/RESOURCE_SESSIONIZATION.md`): a nullable JSON column holding the
`PlanItemSession` provenance of a resource item. Nullable so every pre-existing plan row stays valid unchanged.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008_plan_item_session"
down_revision: Union[str, None] = "0007_observability"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("plan_items", sa.Column("session", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("plan_items", "session")
