"""Planner Agent (A2) — placeholder.

Implemented in Phase 5. Selects/sequences a `WeeklyPlan` from a pre-built
candidate set (IDs only) and writes rationale; also realizes patch edits in
Phase 8. No side-effect tools; output is validated by the Plan Validator
(V1-V10) with a deterministic Fallback Planner behind it (design §8.2, §16).
"""
from __future__ import annotations

from typing import Any

from app.agents.base import Agent


class PlannerAgent(Agent):
    name = "planner"

    async def run(self, run_id: str, input_payload: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("PlannerAgent is implemented in Phase 5 (Planner).")
