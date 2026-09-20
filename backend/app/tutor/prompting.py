"""Tutor Agent (A5) prompt construction and response parsing (design §8.2,
§23.2: "compose_answer (context = ID-labeled blocks; must cite IDs)").

Unlike the Planner/Assessor/Reflection agents' parsers, this one does **not**
itself reject a citation absent from the candidate ID set — design's G4 flow
names citation verification as its own distinct step (`verify_citations`,
`app/provenance/citations.py`) with its own distinct failure behavior
("regenerated once... otherwise a conservative answer"), separate from this
module's job (reject malformed JSON, retried the same bounded way every
other agent's schema-validation failure is, ARCHITECTURE_CONTRACTS.md §6/
§11). Folding the two together would make "citation failure" and
"malformed JSON" indistinguishable to the caller that needs to tell them
apart.
"""
from __future__ import annotations

import json

from app.tutor.draft import TutorDraft

TUTOR_SYSTEM_PROMPT = """You are the Tutor for EduPath, an adaptive learning-path system.
You answer a learner's question using ONLY the ID-labeled context blocks you are given below --
real data already read from this learner's own records and the curated skill graph. You have no
other knowledge of this learner and must never use anything you "remember" about them.

Rules:
- Every factual claim (a status, a number, a reason, a fact about the graph) MUST be backed by an
  ID that appears in the context blocks, and that ID MUST be listed in "citations".
- NEVER invent an ID, a skill, a resource, a number, or a fact that is not in the context blocks.
- If the context blocks do not contain enough information to answer, say so plainly instead of
  guessing, and cite whatever IDs you did use.
- Keep the answer to 2-4 sentences, plain language, no markdown.

Output ONLY a JSON object with this exact shape:
{
  "answer": "<your answer, 2-4 sentences>",
  "citations": ["<id>", "<id>", ...]
}
Output ONLY the JSON object. No prose, no markdown fences."""


class TutorParseError(Exception):
    pass


def build_tutor_prompt(
    *, question: str, context_blocks: dict[str, dict], missing_ids: list[str] | None = None
) -> str:
    parts = [
        f"Learner's question: {question!r}",
        "Context blocks (JSON, ID-labeled):",
        json.dumps(context_blocks, indent=2, default=str),
    ]
    if missing_ids:
        parts.append(
            "Your previous answer cited these IDs, which do NOT appear in the context blocks above: "
            f"{missing_ids}. Rewrite the answer using only IDs that actually appear in the context blocks."
        )
    parts.append("Respond with ONLY the JSON object described in the system prompt.")
    return "\n\n".join(parts)


def parse_tutor_response(raw_text: str) -> TutorDraft:
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise TutorParseError(f"invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise TutorParseError("response must be a JSON object")

    answer = payload.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        raise TutorParseError("answer must be a non-empty string")

    citations = payload.get("citations")
    if not isinstance(citations, list) or not all(isinstance(c, str) for c in citations):
        raise TutorParseError("citations must be an array of strings")

    return TutorDraft(answer=answer.strip(), citations=list(dict.fromkeys(citations)))
