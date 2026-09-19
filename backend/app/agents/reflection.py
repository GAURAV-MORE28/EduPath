"""Reflection Agent (A4, mode b -- evidence-triggered root-cause analysis).
design §8.2, §20. Turns a pre-resolved evidence bundle plus candidate ID
sets (graph-identified root-cause skill candidates, remediation resource
IDs, probe item IDs -- `app/reflection/service.py` builds these) into a
bounded set of plan-edit operators. It cannot free-form rewrite the plan:
output is schema-only, strictly ID-validated against the given candidates
(`app/reflection/prompting.py::parse_reflection_response`), and re-checked
by the deterministic Reflection Validator downstream
(`app/reflection/validator.py`) -- this agent's own output is never trusted
to commit anything by itself (ARCHITECTURE_CONTRACTS.md §7).

Retry policy mirrors the Planner/Profiler Agents (ARCHITECTURE_CONTRACTS.md
§11): schema/ID-validation failure -> retry with the error message fed
back, up to `REFLECTION_MAX_ROUNDS` total, then degrade (`degraded=True`).
Unlike the Profiler, this agent does not embed its own deterministic
fallback -- `app/reflection/service.py` (the caller) decides when to fall
through to `app/reflection/deterministic.py`'s policy, the same split
Phase 5 established between the Planner Agent and the G2 graph's
`fallback_plan` node.
"""
from __future__ import annotations

from typing import Any

from app.agents.base import Agent
from app.core.thresholds import REFLECTION_MAX_ROUNDS
from app.gateway.llm_gateway import LLMRequest, ModelTier
from app.reflection.evidence import EvidenceBundle
from app.reflection.prompting import (
    REFLECTION_SYSTEM_PROMPT,
    ReflectionParseError,
    build_reflection_prompt,
    parse_reflection_response,
)


class ReflectionAgent(Agent):
    name = "reflection"
    max_retries = REFLECTION_MAX_ROUNDS - 1

    async def run(self, run_id: str, input_payload: dict[str, Any]) -> dict[str, Any]:
        bundle: EvidenceBundle = input_payload["bundle"]
        candidate_root_cause_skill_ids: list[str] = input_payload["candidate_root_cause_skill_ids"]
        candidate_resource_ids: list[str] = input_payload["candidate_resource_ids"]
        candidate_probe_item_ids: list[str] = input_payload["candidate_probe_item_ids"]
        validation_feedback: list[str] | None = input_payload.get("validation_feedback")

        base_prompt = build_reflection_prompt(
            bundle,
            candidate_root_cause_skill_ids=candidate_root_cause_skill_ids,
            candidate_resource_ids=candidate_resource_ids,
            candidate_probe_item_ids=candidate_probe_item_ids,
            validation_feedback=validation_feedback,
        )

        last_error: str | None = None
        for _attempt in range(self.max_retries + 1):
            user_prompt = (
                base_prompt
                if last_error is None
                else f"{base_prompt}\n\nYour previous response was invalid: {last_error}\nOutput ONLY the corrected JSON object."
            )
            response = await self.gateway.complete(
                LLMRequest(
                    tier=ModelTier.STRONG,  # design §33.2: causal diagnosis is a strong-tier task
                    system_prompt=REFLECTION_SYSTEM_PROMPT,
                    user_prompt=user_prompt,
                    schema_name="ReflectionResult",
                    temperature=0.0,
                )
            )
            if response.degraded:
                # No provider configured -- deterministic, won't change on retry
                # (this project's permanent default; see the module docstring).
                return {"draft": None, "degraded": True}
            try:
                draft = parse_reflection_response(
                    response.raw_text,
                    bundle,
                    candidate_root_cause_skill_ids=candidate_root_cause_skill_ids,
                    candidate_resource_ids=candidate_resource_ids,
                    candidate_probe_item_ids=candidate_probe_item_ids,
                )
                return {"draft": draft, "degraded": False}
            except ReflectionParseError as exc:
                last_error = str(exc)
                continue

        return {"draft": None, "degraded": True}
