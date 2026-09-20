"""observability: agent_runs, agent_steps, llm_replay_entries

Revision ID: 0007_observability
Revises: 0006_reflection
Create Date: 2026-09-20

Phase 12 (integration + demo hardening): the persisted trace tables of design
§28/§31 and the durable LLM record/replay table of design §33.5 /
ARCHITECTURE_CONTRACTS.md §14. See `backend/app/db/models.py`.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007_observability"
down_revision: Union[str, None] = "0006_reflection"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_runs",
        sa.Column("run_id", sa.String(length=64), primary_key=True),
        sa.Column("user_id", sa.String(length=64), nullable=True),
        sa.Column("learner_id", sa.String(length=36), nullable=True),
        sa.Column("method", sa.String(length=8), nullable=False, server_default=""),
        sa.Column("route", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("graph", sa.String(length=32), nullable=False, server_default="api"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="completed"),
        sa.Column("http_status", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Float(), nullable=False, server_default="0"),
        sa.Column("llm_calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("llm_retries", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("llm_replays", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("llm_degraded", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_in", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_out", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("planner_loops", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("retrieval_ms", sa.Float(), nullable=False, server_default="0"),
        sa.Column("degraded", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("error", sa.Text(), nullable=True),
    )
    op.create_index("ix_agent_runs_user_id", "agent_runs", ["user_id"])
    op.create_index("ix_agent_runs_learner_id", "agent_runs", ["learner_id"])

    op.create_table(
        "agent_steps",
        sa.Column("step_id", sa.String(length=36), primary_key=True),
        sa.Column("run_id", sa.String(length=64), sa.ForeignKey("agent_runs.run_id"), nullable=False),
        sa.Column("learner_id", sa.String(length=36), nullable=True),
        sa.Column("seq", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("actor", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("refs", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("input_ref", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("output_ref", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("decision_id", sa.String(length=36), nullable=True),
        sa.Column("duration_ms", sa.Float(), nullable=False, server_default="0"),
        sa.Column("tokens_in", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_out", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="ok"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_agent_steps_run_id", "agent_steps", ["run_id"])
    op.create_index("ix_agent_steps_learner_id", "agent_steps", ["learner_id"])

    op.create_table(
        "llm_replay_entries",
        sa.Column("prompt_hash", sa.String(length=64), primary_key=True),
        sa.Column("schema_name", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("tier", sa.String(length=16), nullable=False, server_default=""),
        sa.Column("response", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("llm_replay_entries")
    op.drop_table("agent_steps")
    op.drop_table("agent_runs")
