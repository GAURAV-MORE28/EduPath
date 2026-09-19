"""Profiler Agent (A1) — placeholder.

Implemented in Phase 2. Converts uploaded documents into `ExtractedClaims`
(design §8.2, §22). No side-effect tools; output is schema-only; span
verification happens downstream in the Evidence Verifier service, not here.
"""
from __future__ import annotations

from typing import Any

from app.agents.base import Agent


class ProfilerAgent(Agent):
    name = "profiler"

    async def run(self, run_id: str, input_payload: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("ProfilerAgent is implemented in Phase 2 (Learner profiling).")
