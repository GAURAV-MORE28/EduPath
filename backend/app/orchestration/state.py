"""Shared LangGraph run state.

Design §9.2 (Shared run state), P4/P6 (explicit state, bounded autonomy):
every graph run carries typed state plus bounded counters (retries,
reflection rounds, token/wall-clock budgets) rather than free-form agent
memory.
"""
from __future__ import annotations

from typing import Any, TypedDict


class RunCounters(TypedDict, total=False):
    retries: int
    reflection_rounds: int
    planner_attempts: int
    tool_steps: int
    tokens_used: int


class RunState(TypedDict, total=False):
    run_id: str
    learner_id: str
    graph: str
    status: str  # running | needs_user | completed | degraded | failed
    counters: RunCounters
    data: dict[str, Any]
