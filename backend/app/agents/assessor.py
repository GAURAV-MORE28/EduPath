"""Assessor Agent (A3) — placeholder.

Implemented in Phase 7. Generates practice items (distractors drawn from the
misconception catalog) and grades short answers by rubric; MCQ grading stays
deterministic outside this agent (design §8.2, §18).
"""
from __future__ import annotations

from typing import Any

from app.agents.base import Agent


class AssessorAgent(Agent):
    name = "assessor"

    async def run(self, run_id: str, input_payload: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("AssessorAgent is implemented in Phase 7 (Practice + assessment).")
