"""Planner Agent tests (design §8.2): the degrade-to-empty path (no provider
configured, this project's default -- ARCHITECTURE_CONTRACTS.md §11), the
LLM draft path, retry-on-invalid-output (including an *invented* ID, which
must be rejected exactly like malformed JSON -- ARCHITECTURE_CONTRACTS.md
§7), and patch mode. Mirrors `tests/test_profiler_agent.py`'s
`ScriptedLLMGateway` pattern so the retry/success paths are exercised
without a real provider.
"""
from __future__ import annotations

import json

import pytest

from app.agents.planner import PlannerAgent
from app.gateway.llm_gateway import LLMGateway, LLMResponse
from app.planning.candidates import ObjectiveCandidateSet, ResourceCandidateInfo


class ScriptedLLMGateway(LLMGateway):
    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[str] = []

    async def complete(self, request):  # noqa: D102
        self.calls.append(request.user_prompt)
        return self._responses.pop(0)


def _candidate_sets() -> dict[str, ObjectiveCandidateSet]:
    resource = ResourceCandidateInfo(
        resource_id="res.a",
        title="Intro to A",
        url="https://example.org/a",
        type="article",
        duration_min=20,
        modality="read",
        score=1.0,
        score_breakdown={"relevance": 1.0},
    )
    return {
        "obj.a": ObjectiveCandidateSet(
            objective_id="obj.a",
            skill_id="skill.a",
            objective_type="lesson",
            target_level=2,
            current_level=0,
            priority=1.0,
            prerequisite_objective_ids=[],
            resources=[resource],
            practice_item_ids=["item.a.1"],
        )
    }


def _valid_draft_json() -> str:
    return json.dumps(
        {
            "items": [
                {
                    "type": "resource",
                    "objective_id": "obj.a",
                    "skill_id": "skill.a",
                    "resource_id": "res.a",
                    "practice_item_ids": [],
                    "est_minutes": 20,
                    "difficulty": 1,
                    "day_slot": 1,
                    "depends_on": [],
                    "reason_text": "Start here.",
                }
            ],
            "overall_reason": "A focused first week.",
        }
    )


def _draft_json_with_invented_resource_id() -> str:
    return json.dumps(
        {
            "items": [
                {
                    "type": "resource",
                    "objective_id": "obj.a",
                    "skill_id": "skill.a",
                    "resource_id": "res.made-up",  # not in the candidate set -- must be rejected
                    "practice_item_ids": [],
                    "est_minutes": 20,
                    "difficulty": 1,
                    "day_slot": 1,
                    "depends_on": [],
                    "reason_text": "Start here.",
                }
            ],
            "overall_reason": "A focused first week.",
        }
    )


@pytest.mark.asyncio
async def test_degraded_gateway_returns_empty_plan_and_degraded_true():
    """Default project config (LLM_PROVIDER=none) -> the real LLMGateway
    degrades -> the agent must not fabricate a plan, and must signal
    degraded so the caller (G2 graph) falls through to the Fallback Planner."""
    agent = PlannerAgent(LLMGateway())
    result = await agent.run("run-1", {"candidate_sets": _candidate_sets(), "hours_budget_minutes": 100})
    assert result["degraded"] is True
    assert result["plan_items"] == []


@pytest.mark.asyncio
async def test_empty_candidate_sets_is_a_valid_empty_draft_not_a_failure():
    """The 'impossible candidate set' case: nothing to plan from is not an
    error, and does not even need to call the gateway."""
    gateway = ScriptedLLMGateway([])
    agent = PlannerAgent(gateway)
    result = await agent.run("run-1", {"candidate_sets": {}, "hours_budget_minutes": 100})
    assert result == {"plan_items": [], "overall_reason": "", "degraded": False}
    assert gateway.calls == []


@pytest.mark.asyncio
async def test_successful_llm_draft_on_first_attempt():
    gateway = ScriptedLLMGateway([LLMResponse(raw_text=_valid_draft_json(), degraded=False)])
    agent = PlannerAgent(gateway)
    result = await agent.run("run-1", {"candidate_sets": _candidate_sets(), "hours_budget_minutes": 100})

    assert result["degraded"] is False
    assert len(gateway.calls) == 1
    assert result["plan_items"][0]["resource_id"] == "res.a"
    assert result["overall_reason"] == "A focused first week."


@pytest.mark.asyncio
async def test_invalid_json_output_retries_then_succeeds():
    gateway = ScriptedLLMGateway(
        [
            LLMResponse(raw_text="not valid json", degraded=False),
            LLMResponse(raw_text=_valid_draft_json(), degraded=False),
        ]
    )
    agent = PlannerAgent(gateway)
    result = await agent.run("run-1", {"candidate_sets": _candidate_sets(), "hours_budget_minutes": 100})

    assert result["degraded"] is False
    assert len(gateway.calls) == 2
    assert "invalid" in gateway.calls[1].lower()


@pytest.mark.asyncio
async def test_invented_resource_id_is_rejected_like_invalid_output():
    """ARCHITECTURE_CONTRACTS.md §7: 'an LLM never emits a raw URL or invents
    an ID; it selects from a pre-built candidate ID set' -- an invented ID
    must trigger the same retry-then-degrade path as malformed JSON, not be
    silently accepted."""
    gateway = ScriptedLLMGateway(
        [LLMResponse(raw_text=_draft_json_with_invented_resource_id(), degraded=False) for _ in range(3)]
    )
    agent = PlannerAgent(gateway)
    result = await agent.run("run-1", {"candidate_sets": _candidate_sets(), "hours_budget_minutes": 100})

    assert result["degraded"] is True
    assert result["plan_items"] == []
    assert len(gateway.calls) == 3  # 1 initial + 2 retries, ARCHITECTURE_CONTRACTS.md §11
    assert "res.made-up" in gateway.calls[1]  # the retry prompt surfaces the invalid-ID error


@pytest.mark.asyncio
async def test_mid_stream_degrade_stops_retrying():
    gateway = ScriptedLLMGateway(
        [LLMResponse(raw_text="bad", degraded=False), LLMResponse(raw_text="", degraded=True)]
    )
    agent = PlannerAgent(gateway)
    result = await agent.run("run-1", {"candidate_sets": _candidate_sets(), "hours_budget_minutes": 100})

    assert result["degraded"] is True
    assert len(gateway.calls) == 2


# -- patch mode --------------------------------------------------------------


@pytest.mark.asyncio
async def test_patch_mode_includes_existing_items_and_operators_in_the_prompt():
    gateway = ScriptedLLMGateway([LLMResponse(raw_text=_valid_draft_json(), degraded=False)])
    agent = PlannerAgent(gateway)

    existing_items = [{"item_id": "old-1", "type": "resource", "objective_id": "obj.a", "skill_id": "skill.a"}]
    operators = [{"op": "swap_resource", "skill_id": "skill.a", "reason": "learner struggled"}]

    result = await agent.run(
        "run-1",
        {
            "candidate_sets": _candidate_sets(),
            "hours_budget_minutes": 100,
            "mode": "patch",
            "existing_items": existing_items,
            "operators": operators,
        },
    )

    assert result["degraded"] is False
    prompt = gateway.calls[0]
    assert "old-1" in prompt
    assert "swap_resource" in prompt
    assert "Mode: patch" in prompt


@pytest.mark.asyncio
async def test_patch_mode_degrades_like_draft_mode_when_gateway_unavailable():
    agent = PlannerAgent(LLMGateway())
    result = await agent.run(
        "run-1",
        {
            "candidate_sets": _candidate_sets(),
            "hours_budget_minutes": 100,
            "mode": "patch",
            "existing_items": [],
            "operators": [{"op": "swap_resource"}],
        },
    )
    assert result["degraded"] is True
    assert result["plan_items"] == []


@pytest.mark.asyncio
async def test_validation_feedback_is_surfaced_in_the_retry_prompt():
    gateway = ScriptedLLMGateway([LLMResponse(raw_text=_valid_draft_json(), degraded=False)])
    agent = PlannerAgent(gateway)

    await agent.run(
        "run-1",
        {
            "candidate_sets": _candidate_sets(),
            "hours_budget_minutes": 100,
            "validation_feedback": ["plan totals 500 min, exceeding the 100 min budget"],
        },
    )

    assert "exceeding the 100 min budget" in gateway.calls[0]
