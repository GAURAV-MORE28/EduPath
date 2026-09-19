"""Typed inter-component message envelope.

ARCHITECTURE_CONTRACTS.md §6 (Agent I/O contract): all inter-component messages
are typed, schema-validated, and wrapped in this envelope. Free text is only
allowed in fields explicitly marked display-only, and is never parsed downstream.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Generic, TypeVar
from uuid import uuid4

from pydantic import BaseModel, Field

PayloadT = TypeVar("PayloadT")


class AgentMessage(BaseModel, Generic[PayloadT]):
    run_id: str
    step_id: str = Field(default_factory=lambda: str(uuid4()))
    schema_name: str
    schema_version: str = "1.0"
    producer: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    payload: PayloadT
    refs: list[str] = Field(default_factory=list)


class TraceEvent(BaseModel):
    """SSE trace event shape (ARCHITECTURE_CONTRACTS.md §8)."""

    run_id: str
    step_id: str
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    agent_or_service: str
    kind: str  # input | tool_call | graph_query | retrieval | decision | validation | reflection | replan | output | degraded | error
    summary: str
    refs: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)
