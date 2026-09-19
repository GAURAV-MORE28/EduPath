"""Tutor Agent (A5) — placeholder.

Implemented in Phase 9. Read-only tool-calling agent (`get_learner_state`,
`get_gaps`, `get_current_plan`, ...); cannot mutate the plan; every claim
must cite a resolvable ID, verified by the Provenance Service (design §8.2,
§23). Max 4 tool steps per turn.
"""
from __future__ import annotations

from typing import Any

from app.agents.base import Agent


class TutorAgent(Agent):
    name = "tutor"

    async def run(self, run_id: str, input_payload: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("TutorAgent is implemented in Phase 9 (Tutor).")
