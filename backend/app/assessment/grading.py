"""Grading (design §18.1/§9.5's `grade` node): "MCQ: deterministic. Short
answer: rubric-based, small LLM, temperature 0; low-confidence grades
flagged."
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from app.db.models import PracticeItem
from app.gateway.llm_gateway import LLMGateway, LLMRequest, ModelTier

SHORT_ANSWER_SYSTEM_PROMPT = """You are grading a learner's short-answer response against a rubric.
Output ONLY a JSON object: {"correct": true|false, "rationale": "<one short sentence>"}.
"correct" means the response satisfies the rubric's key points, not that it is a verbatim match.
No prose, no markdown fences, JSON only."""


@dataclass(frozen=True)
class McqGradeResult:
    correct: bool
    misconception_id: str | None


def grade_mcq(item: PracticeItem, chosen_option: int) -> McqGradeResult:
    """Deterministic (design §18.1) -- compares `chosen_option` (an index
    into `item.options`) against the option flagged `is_key`. Never trusts
    a client-supplied "correct" flag; always re-derives it server-side from
    the stored key, which the client never receives (design §18.3)."""
    options = item.options
    if chosen_option < 0 or chosen_option >= len(options):
        # Out-of-range index -- can't be the key; no misconception tag to attribute either.
        return McqGradeResult(correct=False, misconception_id=None)
    chosen = options[chosen_option]
    correct = bool(chosen.get("is_key"))
    misconception_id = None if correct else chosen.get("misconception_id")
    return McqGradeResult(correct=correct, misconception_id=misconception_id)


@dataclass(frozen=True)
class ShortAnswerGradeResult:
    correct: bool | None  # None = ungraded (gateway degraded) -- never guessed
    confidence: str  # low | medium | high
    rationale: str
    degraded: bool = False


async def grade_short_answer(gateway: LLMGateway, *, rubric: str, response_text: str) -> ShortAnswerGradeResult:
    """design §18.1: small-LLM, temperature 0, rubric-based; "low-confidence
    grades flagged" -- when the gateway degrades (no provider configured,
    this project's default), the grade is `correct=None` and `confidence="low"`
    rather than a fabricated pass/fail (ARCHITECTURE_CONTRACTS.md §11's
    graceful-degradation contract, applied to grading specifically)."""
    llm_response = await gateway.complete(
        LLMRequest(
            tier=ModelTier.SMALL,
            system_prompt=SHORT_ANSWER_SYSTEM_PROMPT,
            user_prompt=f"Rubric:\n{rubric}\n\nLearner response:\n{response_text}",
            schema_name="ShortAnswerGrade",
            temperature=0.0,
        )
    )
    if llm_response.degraded:
        return ShortAnswerGradeResult(correct=None, confidence="low", rationale="grading unavailable (no LLM provider configured)", degraded=True)

    try:
        parsed = json.loads(llm_response.raw_text)
        correct = bool(parsed["correct"])
        rationale = str(parsed.get("rationale", ""))
    except (json.JSONDecodeError, KeyError, TypeError):
        return ShortAnswerGradeResult(correct=None, confidence="low", rationale="grader returned an unparsable response", degraded=True)

    return ShortAnswerGradeResult(correct=correct, confidence="medium", rationale=rationale, degraded=False)
