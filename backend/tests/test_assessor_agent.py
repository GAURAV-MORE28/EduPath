"""Assessor Agent tests (design §8.2/§18.2): item generation with
misconception-tagged distractors, invented-tag rejection, and blind-solver
validation. Mirrors `tests/test_profiler_agent.py`/`tests/test_planner_agent.py`'s
`ScriptedLLMGateway` pattern.
"""
from __future__ import annotations

import json

import pytest

from app.agents.assessor import AssessorAgent
from app.gateway.llm_gateway import LLMGateway, LLMResponse

pytestmark = pytest.mark.asyncio


class ScriptedLLMGateway(LLMGateway):
    """Returns each response in `responses` in order, one per `complete()` call."""

    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[str] = []

    async def complete(self, request):  # noqa: D102
        self.calls.append(request.user_prompt)
        return self._responses.pop(0)


def _misconceptions() -> list[dict]:
    return [{"misconception_id": "misc.sign_error", "description": "Drops a negative sign."}]


def _valid_generation_json(*, misconception_id: str | None = "misc.sign_error") -> str:
    return json.dumps(
        {
            "items": [
                {
                    "question": "What is -3 + 5?",
                    "difficulty": "easy",
                    "options": [
                        {"text": "2", "is_key": True, "misconception_id": None},
                        {"text": "-2", "is_key": False, "misconception_id": misconception_id},
                        {"text": "8", "is_key": False, "misconception_id": None},
                    ],
                    "explanation": "-3 + 5 = 2.",
                }
            ]
        }
    )


def _base_payload(count: int = 1) -> dict:
    return {"skill_label": "Integer arithmetic", "skill_description": "", "level_label": "foundational", "misconceptions": _misconceptions(), "count": count}


async def test_degraded_gateway_returns_no_generated_items():
    agent = AssessorAgent(LLMGateway())
    result = await agent.run("run-1", _base_payload())
    assert result == {"items": [], "degraded": True}


async def test_successful_generation_and_blind_solver_pass_keeps_the_item():
    gateway = ScriptedLLMGateway(
        [
            LLMResponse(raw_text=_valid_generation_json(), degraded=False),  # generation
            LLMResponse(raw_text=json.dumps({"chosen_index": 0}), degraded=False),  # blind solver picks the key (index 0)
        ]
    )
    agent = AssessorAgent(gateway)
    result = await agent.run("run-1", _base_payload())
    assert result["degraded"] is False
    assert len(result["items"]) == 1
    assert result["items"][0]["options"][1]["misconception_id"] == "misc.sign_error"


async def test_blind_solver_failure_drops_the_item_without_failing_the_run():
    gateway = ScriptedLLMGateway(
        [
            LLMResponse(raw_text=_valid_generation_json(), degraded=False),
            LLMResponse(raw_text=json.dumps({"chosen_index": 1}), degraded=False),  # picks a wrong option -- fails validation
        ]
    )
    agent = AssessorAgent(gateway)
    result = await agent.run("run-1", _base_payload())
    assert result["degraded"] is False
    assert result["items"] == []  # rejected, not silently trusted


async def test_blind_solver_degraded_mid_run_fails_the_item_closed():
    gateway = ScriptedLLMGateway(
        [
            LLMResponse(raw_text=_valid_generation_json(), degraded=False),
            LLMResponse(raw_text="", degraded=True),  # blind solver call itself degrades
        ]
    )
    agent = AssessorAgent(gateway)
    result = await agent.run("run-1", _base_payload())
    assert result["items"] == []
    assert result["degraded"] is False  # generation succeeded; only the item itself was rejected


async def test_invented_misconception_id_is_rejected_and_retried():
    gateway = ScriptedLLMGateway(
        [
            LLMResponse(raw_text=_valid_generation_json(misconception_id="misc.invented"), degraded=False),
            LLMResponse(raw_text=_valid_generation_json(misconception_id="misc.sign_error"), degraded=False),
            LLMResponse(raw_text=json.dumps({"chosen_index": 0}), degraded=False),
        ]
    )
    agent = AssessorAgent(gateway)
    result = await agent.run("run-1", _base_payload())
    assert result["degraded"] is False
    assert len(result["items"]) == 1
    assert "misc.invented" in gateway.calls[1]  # the retry prompt surfaces the invalid-tag error


async def test_generation_exhausts_retries_then_degrades():
    gateway = ScriptedLLMGateway([LLMResponse(raw_text="not json", degraded=False) for _ in range(3)])
    agent = AssessorAgent(gateway)
    result = await agent.run("run-1", _base_payload())
    assert result == {"items": [], "degraded": True}
    assert len(gateway.calls) == 3  # 1 initial + 2 retries, ARCHITECTURE_CONTRACTS.md §11
