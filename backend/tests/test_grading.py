"""Grading tests (`app/assessment/grading.py`): MCQ (deterministic) and
short-answer (small-LLM rubric, degrade-to-ungraded) -- design §18.1/§9.5.
"""
from __future__ import annotations

import json

import pytest

from app.assessment.grading import grade_mcq, grade_short_answer
from app.db.models import PracticeItem
from app.gateway.llm_gateway import LLMGateway, LLMResponse


def _mcq_item() -> PracticeItem:
    return PracticeItem(
        item_id="item.1",
        skill_id="skill.a",
        difficulty="easy",
        purpose="practice",
        stem="What is 2+2?",
        options=[
            {"text": "3", "is_key": False, "misconception_id": "misc.off_by_one"},
            {"text": "4", "is_key": True, "misconception_id": None},
            {"text": "5", "is_key": False, "misconception_id": None},
        ],
        explanation="2+2=4",
    )


def test_grade_mcq_correct_choice():
    result = grade_mcq(_mcq_item(), 1)
    assert result.correct is True
    assert result.misconception_id is None


def test_grade_mcq_incorrect_choice_returns_its_misconception_tag():
    result = grade_mcq(_mcq_item(), 0)
    assert result.correct is False
    assert result.misconception_id == "misc.off_by_one"


def test_grade_mcq_incorrect_choice_with_no_tag_is_a_generic_wrong_answer():
    result = grade_mcq(_mcq_item(), 2)
    assert result.correct is False
    assert result.misconception_id is None


def test_grade_mcq_never_trusts_a_client_correctness_claim():
    """The grader only ever looks at the stored key -- there is no
    'claimed correct' input it could even be fooled by; this test documents
    that guarantee by checking the same index always regrades the same way."""
    item = _mcq_item()
    assert grade_mcq(item, 1).correct is True
    assert grade_mcq(item, 1).correct is True  # idempotent, never state-dependent


def test_grade_mcq_out_of_range_index_is_incorrect_not_a_crash():
    result = grade_mcq(_mcq_item(), 99)
    assert result.correct is False
    assert result.misconception_id is None


class ScriptedLLMGateway(LLMGateway):
    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[str] = []

    async def complete(self, request):  # noqa: D102
        self.calls.append(request.user_prompt)
        return self._responses.pop(0)


@pytest.mark.asyncio
async def test_short_answer_degraded_gateway_is_ungraded_not_guessed():
    result = await grade_short_answer(LLMGateway(), rubric="Must mention gradient descent.", response_text="I used SGD.")
    assert result.correct is None
    assert result.confidence == "low"
    assert result.degraded is True


@pytest.mark.asyncio
async def test_short_answer_successful_grade():
    gateway = ScriptedLLMGateway([LLMResponse(raw_text=json.dumps({"correct": True, "rationale": "Mentions SGD correctly."}), degraded=False)])
    result = await grade_short_answer(gateway, rubric="Must mention gradient descent.", response_text="I used SGD.")
    assert result.correct is True
    assert result.confidence == "medium"
    assert result.degraded is False
    assert "temperature" not in gateway.calls[0]  # sanity: prompt text, not request metadata


@pytest.mark.asyncio
async def test_short_answer_unparsable_response_is_ungraded():
    gateway = ScriptedLLMGateway([LLMResponse(raw_text="not json", degraded=False)])
    result = await grade_short_answer(gateway, rubric="r", response_text="a")
    assert result.correct is None
    assert result.confidence == "low"
    assert result.degraded is True
