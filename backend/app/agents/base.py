"""Agent interface shared by all five LLM agents.

ARCHITECTURE_CONTRACTS.md §2: exactly five LLM agents exist (Profiler,
Planner, Assessor, Reflection, Tutor); none of them may mutate persisted
state directly, and none may run as a free-form autonomous loop — every
agent is invoked from an explicit LangGraph node.

This module defines only the shared shape. Each agent's real prompting,
tool use, and output schema is implemented by the phase that owns it.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.gateway.llm_gateway import LLMGateway


class Agent(ABC):
    """Base class for an LLM agent node.

    Concrete agents are invoked only from orchestrator nodes (never called
    directly from the API layer) and must never be given side-effect tools —
    only validated commit nodes may mutate persisted state.
    """

    name: str

    def __init__(self, gateway: LLMGateway) -> None:
        self.gateway = gateway

    @abstractmethod
    async def run(self, run_id: str, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Execute one bounded unit of work and return a schema-validated payload."""
        raise NotImplementedError
