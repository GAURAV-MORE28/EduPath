"""Reflection Agent (A4) — placeholder.

Implemented in Phase 8. Two modes: (a) plan critique before presentation,
(b) evidence-triggered root-cause analysis producing bounded edit operators
only (design §8.2, §20). Cannot free-form rewrite the plan; the Reflection
Validator (deterministic) must approve before any operator applies.
"""
from __future__ import annotations

from typing import Any

from app.agents.base import Agent


class ReflectionAgent(Agent):
    name = "reflection"

    async def run(self, run_id: str, input_payload: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("ReflectionAgent is implemented in Phase 8 (Reflection / re-planning).")
