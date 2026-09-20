"""Tutor Agent tests (design §8.2/§23.2): the degrade-to-None path (no
provider configured, this project's default), a valid LLM draft, and
retry-on-malformed-JSON. Mirrors `tests/test_reflection_agent.py`'s
`ScriptedLLMGateway` pattern. Citation-existence *verification* is
deliberately NOT this agent's job (see `app/tutor/prompting.py`'s module
docstring) -- that is `app/provenance/citations.py`, tested separately.
"""
from __future__ import annotations

import json

import pytest

from app.agents.tutor import TutorAgent
from app.gateway.llm_gateway import LLMGateway, LLMResponse
from app.tutor.draft import TutorDraft

pytestmark = pytest.mark.asyncio


class ScriptedLLMGateway(LLMGateway):
    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[str] = []

    async def complete(self, request):  # noqa: D102
        self.calls.append(request.user_prompt)
        return self._responses.pop(0)


def _run_kwargs(**overrides) -> dict:
    base = {
        "question": "Why do I need the chain rule?",
        "context_blocks": {"explain_skill_path": {"skill_id": "skill.chain_rule", "path": []}},
        "missing_ids": None,
    }
    base.update(overrides)
    return base


def _valid_response_json() -> str:
    return json.dumps({"answer": "It's a prerequisite for backpropagation.", "citations": ["skill.chain_rule"]})


async def test_degrades_to_none_when_no_provider_configured():
    agent = TutorAgent(LLMGateway())  # LLM_PROVIDER=none by default
    result = await agent.run("run-1", _run_kwargs())
    assert result["degraded"] is True
    assert result["draft"] is None


async def test_valid_llm_draft_is_parsed():
    gateway = ScriptedLLMGateway([LLMResponse(raw_text=_valid_response_json(), degraded=False)])
    agent = TutorAgent(gateway)
    result = await agent.run("run-1", _run_kwargs())
    assert result["degraded"] is False
    draft: TutorDraft = result["draft"]
    assert draft.answer == "It's a prerequisite for backpropagation."
    assert draft.citations == ["skill.chain_rule"]


async def test_malformed_json_is_retried_then_succeeds():
    gateway = ScriptedLLMGateway(
        [LLMResponse(raw_text="not json", degraded=False), LLMResponse(raw_text=_valid_response_json(), degraded=False)]
    )
    agent = TutorAgent(gateway)
    result = await agent.run("run-1", _run_kwargs())
    assert result["degraded"] is False
    assert len(gateway.calls) == 2
    assert "invalid" in gateway.calls[1].lower()


async def test_exhausted_retries_degrades():
    gateway = ScriptedLLMGateway([LLMResponse(raw_text="not json", degraded=False)] * (TutorAgent.max_retries + 1))
    agent = TutorAgent(gateway)
    result = await agent.run("run-1", _run_kwargs())
    assert result["degraded"] is True
    assert result["draft"] is None


async def test_missing_answer_field_is_a_parse_error():
    gateway = ScriptedLLMGateway(
        [LLMResponse(raw_text=json.dumps({"citations": ["skill.chain_rule"]}), degraded=False)] * (TutorAgent.max_retries + 1)
    )
    agent = TutorAgent(gateway)
    result = await agent.run("run-1", _run_kwargs())
    assert result["degraded"] is True
