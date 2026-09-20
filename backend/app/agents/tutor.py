"""Tutor Agent (A5, design §8.2, §23.2's `compose_answer`). Turns a question
plus already-fetched, ID-labeled tool-call context blocks into a grounded
answer. It cannot mutate anything (no side-effect tools are ever handed to
it, ARCHITECTURE_CONTRACTS.md §13) and it never chooses its own tool calls —
`app/tutor/intent.py`'s rule-based `classify_intent`/`plan_tools` already
decided which tools ran before this agent is invoked at all (design §9.6:
`classify_intent -> plan_tools -> call_tools -> compose_answer`).

Retry policy mirrors every other agent (ARCHITECTURE_CONTRACTS.md §6/§11):
malformed-JSON/schema failure -> retry with the error fed back, up to
`max_retries`, then degrade. This is deliberately a *different* retry than
the "regenerate once on citation failure" loop design §9.6 describes — that
one lives one layer up, in `app/tutor/service.py`, since it needs the
Provenance Service's `verify_citations` result (which this agent has no
access to) to know whether to retry at all. See `app/tutor/prompting.py`'s
module docstring for the full split.
"""
from __future__ import annotations

from typing import Any

from app.agents.base import Agent
from app.gateway.llm_gateway import LLMRequest, ModelTier
from app.tutor.prompting import TUTOR_SYSTEM_PROMPT, TutorParseError, build_tutor_prompt, parse_tutor_response

TUTOR_AGENT_MAX_RETRIES = 2


class TutorAgent(Agent):
    name = "tutor"
    max_retries = TUTOR_AGENT_MAX_RETRIES

    async def run(self, run_id: str, input_payload: dict[str, Any]) -> dict[str, Any]:
        question: str = input_payload["question"]
        context_blocks: dict[str, dict] = input_payload["context_blocks"]
        missing_ids: list[str] | None = input_payload.get("missing_ids")

        base_prompt = build_tutor_prompt(question=question, context_blocks=context_blocks, missing_ids=missing_ids)

        last_error: str | None = None
        for _attempt in range(self.max_retries + 1):
            user_prompt = (
                base_prompt
                if last_error is None
                else f"{base_prompt}\n\nYour previous response was invalid: {last_error}\nOutput ONLY the corrected JSON object."
            )
            response = await self.gateway.complete(
                LLMRequest(
                    tier=ModelTier.STRONG,  # design §33.2: "grounded dialogue" is a strong-tier task
                    system_prompt=TUTOR_SYSTEM_PROMPT,
                    user_prompt=user_prompt,
                    schema_name="TutorAnswer",
                    temperature=0.0,
                )
            )
            if response.degraded:
                # No provider configured -- deterministic, won't change on retry
                # (this project's permanent default; see the module docstring).
                return {"draft": None, "degraded": True}
            try:
                draft = parse_tutor_response(response.raw_text)
                return {"draft": draft, "degraded": False}
            except TutorParseError as exc:
                last_error = str(exc)
                continue

        return {"draft": None, "degraded": True}
