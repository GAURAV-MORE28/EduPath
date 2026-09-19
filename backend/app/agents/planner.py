"""Planner Agent (A2) — design §8.2, §16. Turns a pre-built, ID-only
candidate set (`app/planning/candidates.py`, itself built from the Gap
Engine's `LearningObjective[]`, Phase 4, and the Resource Retriever/Ranker's
`ResourceRecommendation[]`, Phase 6) into a sequenced draft plan. No
side-effect tools; output is schema-only and re-validated deterministically
downstream (the Plan Validator, `app/planning/validator.py`) -- this agent's
own output is never trusted to commit anything by itself.

Two modes (design §8.2's "draft / patch"):
  - `"draft"` (`create_plan`): propose an initial week's plan from candidates.
  - `"patch"` (`patch_existing_plan`): given an existing plan's items and a
    closed set of edit operators (design §20.5, Reflection's vocabulary --
    Phase 8, not implemented yet), propose a revised item list. Patch mode
    exists now so Reflection (Phase 8) has something to call; this phase
    does not itself decide *when* to patch (see `app/planning/service.py`).

Retry policy mirrors the Profiler Agent (ARCHITECTURE_CONTRACTS.md §11):
schema/ID-validation failure -> retry with the error message, max 2 times,
then degrade (`degraded=True`, empty items). Unlike the Profiler, this agent
does **not** embed its own deterministic fallback -- the G2 Planning graph's
`fallback_plan` node (`app/planning/fallback.py`) is a *separate* node per
design §9.4's table (`plan_draft` vs `fallback_plan`), so the caller (the
graph, not this agent) decides when to fall through to it.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from app.agents.base import Agent
from app.gateway.llm_gateway import LLMRequest, ModelTier
from app.planning.candidates import ObjectiveCandidateSet
from app.planning.prompting import (
    PLANNER_SYSTEM_PROMPT,
    PlannerParseError,
    build_planner_prompt,
    parse_planner_response,
)


class PlannerAgent(Agent):
    name = "planner"
    max_retries = 2  # ARCHITECTURE_CONTRACTS.md §11

    async def run(self, run_id: str, input_payload: dict[str, Any]) -> dict[str, Any]:
        candidate_sets: dict[str, ObjectiveCandidateSet] = input_payload["candidate_sets"]
        hours_budget_minutes: float = input_payload["hours_budget_minutes"]
        mode: str = input_payload.get("mode", "draft")
        existing_items: list[dict] | None = input_payload.get("existing_items")
        operators: list[dict] | None = input_payload.get("operators")
        validation_feedback: list[str] | None = input_payload.get("validation_feedback")

        if not candidate_sets:
            # Nothing to plan from (the "impossible candidate set" case) --
            # not a failure. The Plan Validator and Fallback Planner both
            # already treat an empty plan as valid, per ARCHITECTURE_CONTRACTS.md §10.
            return {"plan_items": [], "overall_reason": "", "degraded": False}

        base_prompt = build_planner_prompt(
            candidate_sets=candidate_sets,
            hours_budget_minutes=hours_budget_minutes,
            mode=mode,
            existing_items=existing_items,
            operators=operators,
            validation_feedback=validation_feedback,
        )

        last_error: str | None = None
        for _attempt in range(self.max_retries + 1):
            user_prompt = (
                base_prompt
                if last_error is None
                else f"{base_prompt}\n\nYour previous response was invalid: {last_error}\n"
                "Output ONLY the corrected JSON object."
            )
            response = await self.gateway.complete(
                LLMRequest(
                    tier=ModelTier.MID,  # design §33.2: planning is a mid-tier structured-output task
                    system_prompt=PLANNER_SYSTEM_PROMPT,
                    user_prompt=user_prompt,
                    schema_name="PlannerDraft",
                    temperature=0.0,
                )
            )
            if response.degraded:
                # No provider configured -- deterministic, won't change on retry.
                return {"plan_items": [], "overall_reason": "", "degraded": True}
            try:
                drafts, overall_reason = parse_planner_response(response.raw_text, candidate_sets)
                return {
                    "plan_items": [asdict(d) for d in drafts],
                    "overall_reason": overall_reason,
                    "degraded": False,
                }
            except PlannerParseError as exc:
                last_error = str(exc)
                continue

        return {"plan_items": [], "overall_reason": "", "degraded": True}
