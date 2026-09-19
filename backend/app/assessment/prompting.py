"""Assessor Agent (A3) prompt construction and response parsing (design
§8.2, §18.2): item generation with distractors tagged to catalogued
misconceptions, and blind-solver validation. Mirrors
`app/planning/prompting.py`'s split for the Planner Agent -- a system
prompt, a builder that serializes already ID-resolved input, and a parser
that validates the LLM's JSON strictly before anything downstream sees it.

**The LLM does not invent misconception tags** (design §18.2 point 3):
`parse_generation_response` rejects any `misconception_id` not present in
the candidate set handed in, exactly like `app/planning/prompting.py`
rejects an invented resource_id (ARCHITECTURE_CONTRACTS.md §7).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

_VALID_DIFFICULTIES = {"easy", "medium", "hard"}

GENERATION_SYSTEM_PROMPT = """You are the Assessor for EduPath, an adaptive learning-path system.
Generate multiple-choice questions (MCQs) for the given skill and difficulty level.

Output ONLY a JSON object with this exact shape:
{
  "items": [
    {
      "question": "<the question stem>",
      "difficulty": "easy" | "medium" | "hard",
      "options": [
        {"text": "<option text>", "is_key": true|false, "misconception_id": "<id from the given candidates, or null>"}
      ],
      "explanation": "<one short sentence explaining the correct answer>"
    }
  ]
}

Rules:
- Exactly ONE option per item must have "is_key": true.
- Every wrong option ("is_key": false) should be tagged with the misconception_id from the given
  candidate list that it most plausibly reflects, or null if it is just a generic wrong answer.
- You MUST NOT invent a misconception_id -- only use IDs from the candidate list given to you, or null.
- Each item must have between 3 and 5 options.
Output ONLY the JSON object. No prose, no markdown fences."""

BLIND_SOLVER_SYSTEM_PROMPT = """You are answering a multiple-choice question. You do not know which option is
correct -- work it out yourself. Output ONLY a JSON object: {"chosen_index": <integer>}.
No prose, no markdown fences."""


class AssessorParseError(Exception):
    pass


@dataclass(frozen=True)
class GeneratedOption:
    text: str
    is_key: bool
    misconception_id: str | None


@dataclass(frozen=True)
class GeneratedItemDraft:
    question: str
    difficulty: str
    options: list[GeneratedOption] = field(default_factory=list)
    explanation: str = ""

    @property
    def key_index(self) -> int:
        for i, o in enumerate(self.options):
            if o.is_key:
                return i
        raise AssessorParseError("no key option found")  # unreachable if parsed via parse_generation_response


def build_generation_prompt(
    *, skill_label: str, skill_description: str, level_label: str, misconceptions: list[dict], count: int
) -> str:
    candidates = [{"misconception_id": m["misconception_id"], "description": m["description"]} for m in misconceptions]
    parts = [
        f"Skill: {skill_label}",
        f"Skill description: {skill_description}" if skill_description else "",
        f"Target difficulty level: {level_label}",
        f"Generate {count} item(s).",
        "Catalogued misconceptions for this skill (JSON) -- tag distractors from this set only:",
        json.dumps(candidates, indent=2),
        "Respond with ONLY the JSON object described in the system prompt.",
    ]
    return "\n\n".join(p for p in parts if p)


def parse_generation_response(raw_text: str, *, candidate_misconception_ids: set[str]) -> list[GeneratedItemDraft]:
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise AssessorParseError(f"invalid JSON: {exc}") from exc

    if not isinstance(payload, dict) or "items" not in payload or not isinstance(payload["items"], list):
        raise AssessorParseError("response must be a JSON object with an 'items' array")

    drafts: list[GeneratedItemDraft] = []
    for i, raw in enumerate(payload["items"]):
        if not isinstance(raw, dict):
            raise AssessorParseError(f"item {i} is not a JSON object")

        difficulty = raw.get("difficulty")
        if difficulty not in _VALID_DIFFICULTIES:
            raise AssessorParseError(f"item {i}: invalid difficulty {difficulty!r}")

        raw_options = raw.get("options")
        if not isinstance(raw_options, list) or not (3 <= len(raw_options) <= 5):
            raise AssessorParseError(f"item {i}: must have 3-5 options")

        options: list[GeneratedOption] = []
        key_count = 0
        for j, raw_opt in enumerate(raw_options):
            if not isinstance(raw_opt, dict) or not isinstance(raw_opt.get("text"), str):
                raise AssessorParseError(f"item {i} option {j}: missing text")
            is_key = bool(raw_opt.get("is_key"))
            key_count += int(is_key)
            misconception_id = raw_opt.get("misconception_id")
            if misconception_id is not None and misconception_id not in candidate_misconception_ids:
                raise AssessorParseError(f"item {i} option {j}: invented misconception_id {misconception_id!r}")
            if is_key and misconception_id is not None:
                raise AssessorParseError(f"item {i} option {j}: the key option must not carry a misconception tag")
            options.append(GeneratedOption(text=raw_opt["text"], is_key=is_key, misconception_id=misconception_id))

        if key_count != 1:
            raise AssessorParseError(f"item {i}: expected exactly one key option, found {key_count}")

        question = raw.get("question")
        if not isinstance(question, str) or not question.strip():
            raise AssessorParseError(f"item {i}: missing question")

        drafts.append(
            GeneratedItemDraft(
                question=question, difficulty=difficulty, options=options, explanation=str(raw.get("explanation", ""))
            )
        )

    if not drafts:
        raise AssessorParseError("no items generated")
    return drafts


def build_blind_solver_prompt(item: GeneratedItemDraft) -> str:
    options_payload = [{"index": i, "text": o.text} for i, o in enumerate(item.options)]
    return (
        f"Question: {item.question}\n\nOptions (JSON):\n{json.dumps(options_payload, indent=2)}\n\n"
        "Respond with ONLY the JSON object described in the system prompt."
    )


def parse_blind_solver_response(raw_text: str, *, n_options: int) -> int:
    try:
        payload = json.loads(raw_text)
        chosen_index = int(payload["chosen_index"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise AssessorParseError(f"invalid blind-solver response: {exc}") from exc
    if not (0 <= chosen_index < n_options):
        raise AssessorParseError(f"chosen_index {chosen_index} out of range")
    return chosen_index
