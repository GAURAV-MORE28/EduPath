"""Assessor Agent (A3) — design §8.2, §18.2. Generates MCQ items for a
skill/level when the curated item bank is short, with every distractor
tagged to a catalogued `Misconception` ID (or `None`, a generic wrong
answer) -- never an invented tag (ARCHITECTURE_CONTRACTS.md §7, enforced by
`app/assessment/prompting.py`'s `parse_generation_response`). Every
generated item is then **blind-solver validated**: a small-tier model
answers without seeing the key, and must select it, before the item is
trusted (design §18.2 point 4).

Two model tiers (design §33.2: "strong for generation; small for validation
and grading"). No side-effect tools; output is schema-only, exactly like the
Planner and Profiler agents -- storing a validated item in the bank
(`app/assessment/item_bank.py`) happens outside this agent, at the
orchestration layer.

**Graceful degradation:** unlike the Profiler (which has a deterministic
fallback extractor) or the Planner (whose G2 graph has a separate Fallback
Planner node), there is no offline item-generation stand-in -- when no LLM
provider is configured (this project's default), this agent returns no
generated items at all. The item-bank-first step
(`app/assessment/item_bank.py`) still works fully offline; only the
generate-if-short path needs a real provider, same posture as the VLM
Gateway's "no offline OCR stand-in" (Phase 2).
"""
from __future__ import annotations

from typing import Any

from app.agents.base import Agent
from app.observability.context import note_retry
from app.assessment.prompting import (
    BLIND_SOLVER_SYSTEM_PROMPT,
    GENERATION_SYSTEM_PROMPT,
    AssessorParseError,
    GeneratedItemDraft,
    build_blind_solver_prompt,
    build_generation_prompt,
    parse_blind_solver_response,
    parse_generation_response,
)
from app.core.thresholds import ASSESSOR_MAX_RETRIES
from app.gateway.llm_gateway import LLMRequest, ModelTier


class AssessorAgent(Agent):
    name = "assessor"
    max_retries = ASSESSOR_MAX_RETRIES  # ARCHITECTURE_CONTRACTS.md §11

    async def run(self, run_id: str, input_payload: dict[str, Any]) -> dict[str, Any]:
        skill_label: str = input_payload["skill_label"]
        skill_description: str = input_payload.get("skill_description", "")
        level_label: str = input_payload.get("level_label", "")
        misconceptions: list[dict] = input_payload.get("misconceptions", [])
        count: int = input_payload.get("count", 3)

        drafts, degraded = await self._generate(skill_label, skill_description, level_label, misconceptions, count)
        if degraded or not drafts:
            return {"items": [], "degraded": degraded}

        validated: list[GeneratedItemDraft] = []
        for draft in drafts:
            passed = await self._blind_solve_validate(draft)
            if passed:
                validated.append(draft)

        return {
            "items": [
                {
                    "question": d.question,
                    "difficulty": d.difficulty,
                    "options": [{"text": o.text, "is_key": o.is_key, "misconception_id": o.misconception_id} for o in d.options],
                    "explanation": d.explanation,
                }
                for d in validated
            ],
            "degraded": False,
        }

    async def _generate(
        self, skill_label: str, skill_description: str, level_label: str, misconceptions: list[dict], count: int
    ) -> tuple[list[GeneratedItemDraft], bool]:
        candidate_ids = {m["misconception_id"] for m in misconceptions}
        base_prompt = build_generation_prompt(
            skill_label=skill_label, skill_description=skill_description, level_label=level_label,
            misconceptions=misconceptions, count=count,
        )
        last_error: str | None = None

        for _attempt in range(self.max_retries + 1):
            if _attempt > 0:
                note_retry()
            user_prompt = (
                base_prompt
                if last_error is None
                else f"{base_prompt}\n\nYour previous response was invalid: {last_error}\n"
                "Output ONLY the corrected JSON object."
            )
            response = await self.gateway.complete(
                LLMRequest(
                    tier=ModelTier.STRONG,  # design §33.2: item generation is a strong-tier task
                    system_prompt=GENERATION_SYSTEM_PROMPT,
                    user_prompt=user_prompt,
                    schema_name="AssessorGeneratedItems",
                    temperature=0.0,
                )
            )
            if response.degraded:
                return [], True
            try:
                return parse_generation_response(response.raw_text, candidate_misconception_ids=candidate_ids), False
            except AssessorParseError as exc:
                last_error = str(exc)
                continue

        return [], True

    async def _blind_solve_validate(self, draft: GeneratedItemDraft) -> bool:
        """design §18.2 point 4: "a small model answers without the key. It
        must select the key." A degraded gateway (or an unparsable
        blind-solver response) fails the item closed -- never trusted
        without a passing validation."""
        response = await self.gateway.complete(
            LLMRequest(
                tier=ModelTier.SMALL,
                system_prompt=BLIND_SOLVER_SYSTEM_PROMPT,
                user_prompt=build_blind_solver_prompt(draft),
                schema_name="BlindSolverAnswer",
                temperature=0.0,
            )
        )
        if response.degraded:
            return False
        try:
            chosen_index = parse_blind_solver_response(response.raw_text, n_options=len(draft.options))
        except AssessorParseError:
            return False
        return chosen_index == draft.key_index
