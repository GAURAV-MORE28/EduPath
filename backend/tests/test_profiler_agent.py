"""Profiler Agent tests (design §8.2): the LLM path (retried up to 2x on
schema failure, ARCHITECTURE_CONTRACTS.md §11) and the deterministic
fallback used when the gateway degrades. `LLM_PROVIDER=none` is this
project's default (see `tests/conftest.py`), so the no-provider path is
exercised through the real `LLMGateway`; the retry/success paths are
exercised through a stub gateway.
"""
from __future__ import annotations

import json

import pytest

from app.agents.profiler import ProfilerAgent
from app.gateway.llm_gateway import LLMGateway, LLMResponse
from app.profiling.claim_extraction import DeterministicClaimExtractor, SkillPhrase


def _fallback_extractor() -> DeterministicClaimExtractor:
    return DeterministicClaimExtractor([SkillPhrase(phrase="Python", skill_id="skill.python", area="python")])


class ScriptedLLMGateway(LLMGateway):
    """Returns each response in `responses` in order, one per `complete()` call."""

    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[str] = []

    async def complete(self, request):  # noqa: D102
        self.calls.append(request.user_prompt)
        return self._responses.pop(0)


def _valid_claims_json(source_doc_id: str) -> str:
    return json.dumps(
        [
            {
                "label": "Python",
                "category": "python",
                "context_type": "skills_list",
                "claimed_level_cue": None,
                "verbatim_span": "Python",
                "source_doc_id": source_doc_id,
                "span_offsets": {"start": 0, "end": 6},
            }
        ]
    )


@pytest.mark.asyncio
async def test_degraded_gateway_falls_back_to_deterministic_extraction():
    """Default project config (LLM_PROVIDER=none) -> the real LLMGateway
    degrades -> ProfilerAgent must fall back, not return nothing."""
    agent = ProfilerAgent(LLMGateway(), _fallback_extractor())
    result = await agent.run("run-1", {"document_text": "Skills: Python, SQL", "source_doc_id": "doc-1"})
    assert result["degraded"] is True
    assert [c["label"] for c in result["claims"]] == ["Python"]


@pytest.mark.asyncio
async def test_successful_llm_extraction_on_first_attempt():
    gateway = ScriptedLLMGateway([LLMResponse(raw_text=_valid_claims_json("doc-1"), degraded=False)])
    agent = ProfilerAgent(gateway, _fallback_extractor())
    result = await agent.run("run-1", {"document_text": "Skills: Python", "source_doc_id": "doc-1"})
    assert result["degraded"] is False
    assert len(gateway.calls) == 1
    assert [c["label"] for c in result["claims"]] == ["Python"]


@pytest.mark.asyncio
async def test_retries_once_after_invalid_json_then_succeeds():
    gateway = ScriptedLLMGateway(
        [
            LLMResponse(raw_text="not valid json", degraded=False),
            LLMResponse(raw_text=_valid_claims_json("doc-1"), degraded=False),
        ]
    )
    agent = ProfilerAgent(gateway, _fallback_extractor())
    result = await agent.run("run-1", {"document_text": "Skills: Python", "source_doc_id": "doc-1"})
    assert result["degraded"] is False
    assert len(gateway.calls) == 2
    # the retry prompt should include the earlier error so the model can self-correct
    assert "invalid" in gateway.calls[1].lower()


@pytest.mark.asyncio
async def test_exhausts_retries_then_falls_back_to_deterministic():
    gateway = ScriptedLLMGateway([LLMResponse(raw_text="bad", degraded=False) for _ in range(3)])
    agent = ProfilerAgent(gateway, _fallback_extractor())
    result = await agent.run("run-1", {"document_text": "Skills: Python", "source_doc_id": "doc-1"})
    assert result["degraded"] is True
    assert len(gateway.calls) == 3  # 1 initial + 2 retries, ARCHITECTURE_CONTRACTS.md §11
    assert [c["label"] for c in result["claims"]] == ["Python"]


@pytest.mark.asyncio
async def test_mid_stream_degrade_stops_retrying_and_falls_back():
    gateway = ScriptedLLMGateway(
        [LLMResponse(raw_text="bad", degraded=False), LLMResponse(raw_text="", degraded=True)]
    )
    agent = ProfilerAgent(gateway, _fallback_extractor())
    result = await agent.run("run-1", {"document_text": "Skills: Python", "source_doc_id": "doc-1"})
    assert result["degraded"] is True
    assert len(gateway.calls) == 2  # stops as soon as the gateway reports degraded, no further retries
