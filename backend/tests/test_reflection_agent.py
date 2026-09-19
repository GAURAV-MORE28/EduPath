"""Reflection Agent tests (design §8.2/§20.4): the degrade-to-None path (no
provider configured, this project's default), a valid LLM draft, and
retry-on-invalid-output (including an *invented* ID, ARCHITECTURE_CONTRACTS.md
§7). Mirrors `tests/test_planner_agent.py`'s `ScriptedLLMGateway` pattern.
"""
from __future__ import annotations

import json

import pytest

from app.agents.reflection import ReflectionAgent
from app.assessment.struggle import StruggleSignalEntry
from app.gateway.llm_gateway import LLMGateway, LLMResponse
from app.reflection.draft import ReflectionDraft
from app.reflection.evidence import EvidenceBundle

pytestmark = pytest.mark.asyncio


class ScriptedLLMGateway(LLMGateway):
    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[str] = []

    async def complete(self, request):  # noqa: D102
        self.calls.append(request.user_prompt)
        return self._responses.pop(0)


def _bundle() -> EvidenceBundle:
    signal = StruggleSignalEntry(
        signal_class="missing_prerequisite", skill_id="skill.b", confidence="high",
        evidence_ids=["item.1"], counts={"prerequisite_skill_id": "skill.a"}, signal_id="signal-1",
    )
    return EvidenceBundle(
        learner_id="learner-1", struggling_skill_id="skill.b", triggering_signal=signal, all_signals=[signal],
        learner_assessment_item_ids=frozenset({"item.1"}),
    )


def _valid_response_json() -> str:
    return json.dumps(
        {
            "root_cause_class": "missing_prerequisite",
            "root_cause_skill_id": "skill.a",
            "misconception_id": None,
            "evidence_ids": ["item.1"],
            "hypothesis": "chain rule gap",
            "confidence": "high",
            "path_decision": "patch",
            "operators": [
                {"op": "INSERT_REMEDIATION", "params": {"skill_id": "skill.a", "resource_ids": ["res.remedy"]}},
                {"op": "ADD_PROBE", "params": {"skill_id": "skill.a", "purpose": "resolution-check", "practice_item_ids": ["p1"]}},
            ],
            "critique": "",
            "learner_explanation_draft": "we added a remediation",
        }
    )


def _run_kwargs() -> dict:
    return {
        "bundle": _bundle(),
        "candidate_root_cause_skill_ids": ["skill.a", "skill.b"],
        "candidate_resource_ids": ["res.remedy"],
        "candidate_probe_item_ids": ["p1"],
    }


async def test_degrades_to_none_when_no_provider_configured():
    agent = ReflectionAgent(LLMGateway())  # LLM_PROVIDER=none by default
    result = await agent.run("run-1", _run_kwargs())
    assert result["degraded"] is True
    assert result["draft"] is None


async def test_valid_llm_draft_is_parsed():
    gateway = ScriptedLLMGateway([LLMResponse(raw_text=_valid_response_json(), degraded=False)])
    agent = ReflectionAgent(gateway)
    result = await agent.run("run-1", _run_kwargs())
    assert result["degraded"] is False
    draft: ReflectionDraft = result["draft"]
    assert draft.root_cause_skill_id == "skill.a"
    assert draft.operators[0]["op"] == "INSERT_REMEDIATION"


async def test_invented_root_cause_skill_id_is_rejected_and_retried():
    invalid = json.loads(_valid_response_json())
    invalid["root_cause_skill_id"] = "skill.invented"
    gateway = ScriptedLLMGateway(
        [
            LLMResponse(raw_text=json.dumps(invalid), degraded=False),
            LLMResponse(raw_text=_valid_response_json(), degraded=False),
        ]
    )
    agent = ReflectionAgent(gateway)
    result = await agent.run("run-1", _run_kwargs())
    assert result["degraded"] is False
    assert result["draft"].root_cause_skill_id == "skill.a"
    assert len(gateway.calls) == 2
    assert "invalid" in gateway.calls[1].lower() or "not among" in gateway.calls[1].lower()


async def test_exhausting_retries_degrades():
    invalid = json.loads(_valid_response_json())
    invalid["operators"] = [{"op": "NOT_A_REAL_OP", "params": {}}]
    gateway = ScriptedLLMGateway([LLMResponse(raw_text=json.dumps(invalid), degraded=False) for _ in range(5)])
    agent = ReflectionAgent(gateway)
    result = await agent.run("run-1", _run_kwargs())
    assert result["degraded"] is True
    assert result["draft"] is None
