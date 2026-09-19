"""Planner Agent (A2) prompt construction and response parsing (design §8.2,
§16.3 point 4: "selects and sequences *from candidate IDs only*, assigns day
slots, and writes per-item reason... and an overall_reason").

Mirrors `app/profiling/claim_extraction.py`'s split for the Profiler: a
system prompt, a builder that serializes the (already ID-resolved) input into
the user prompt, and a parser that validates the LLM's JSON strictly against
the candidate ID set before anything downstream ever sees it
(ARCHITECTURE_CONTRACTS.md §7: "an LLM never emits a raw URL or invents an
ID; it selects from a pre-built candidate ID set" -- enforced here, not
trusted).
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field

from app.planning.candidates import ObjectiveCandidateSet

PLANNER_SYSTEM_PROMPT = """You are the Planner for EduPath, an adaptive learning-path system.
You will be given a weekly time budget (minutes) and a list of learning objectives, each with a
pre-built candidate set: eligible resource IDs (already ranked, already filtered for eligibility)
and practice/probe item IDs. You must select and sequence items ONLY from these candidate IDs --
you may never invent a resource_id, practice_item_id, objective_id, or skill_id.

Output ONLY a JSON object with this exact shape:
{
  "items": [
    {
      "type": "resource" | "practice" | "probe" | "project" | "review",
      "objective_id": "<one of the given objective_ids>",
      "skill_id": "<the objective's skill_id>",
      "resource_id": "<a resource_id from that objective's candidates, or null>",
      "practice_item_ids": ["<practice_item_id from that objective's candidates>", ...],
      "est_minutes": <integer>,
      "difficulty": <integer 1-3>,
      "day_slot": <integer 1-5>,
      "depends_on": ["<item_id of another item in this same response, if any>", ...],
      "reason_text": "<one short learner-facing sentence>"
    }
  ],
  "overall_reason": "<one short learner-facing paragraph>"
}

Rules:
- A "probe" item must use practice_item_ids from that objective's candidates and no resource_id.
- A "resource" item must use a resource_id from that objective's candidates.
- Stay within the given time budget. Prefer higher-priority objectives first.
- Respect prerequisite order: do not schedule a lesson on a skill before its hard prerequisites
  are met or scheduled earlier (day_slot), unless the prerequisite only needs a probe first.
Output ONLY the JSON object. No prose, no markdown fences."""


class PlannerParseError(Exception):
    pass


@dataclass(frozen=True)
class PlanItemDraft:
    """Framework-independent shape the parser emits -- validated against the
    candidate ID set, but not yet an `app.schemas.common.PlanItem` (which
    requires a durable `item_id`; this assigns one if the LLM omitted it)."""

    item_id: str
    type: str
    objective_id: str
    skill_id: str
    resource_id: str | None
    practice_item_ids: list[str]
    est_minutes: int
    difficulty: int
    day_slot: int
    depends_on: list[str] = field(default_factory=list)
    reason_text: str = ""


_VALID_TYPES = {"resource", "practice", "probe", "project", "review"}


def build_planner_prompt(
    *,
    candidate_sets: dict[str, ObjectiveCandidateSet],
    hours_budget_minutes: float,
    mode: str,
    existing_items: list[dict] | None = None,
    operators: list[dict] | None = None,
    validation_feedback: list[str] | None = None,
) -> str:
    objectives_payload = [
        {
            "objective_id": cs.objective_id,
            "skill_id": cs.skill_id,
            "objective_type": cs.objective_type,
            "target_level": cs.target_level,
            "current_level": cs.current_level,
            "priority": round(cs.priority, 3),
            "candidate_resources": [
                {"resource_id": r.resource_id, "title": r.title, "type": r.type, "duration_min": r.duration_min, "modality": r.modality}
                for r in cs.resources
            ],
            "candidate_practice_item_ids": cs.practice_item_ids,
        }
        for cs in sorted(candidate_sets.values(), key=lambda c: -c.priority)
    ]

    parts = [
        f"Weekly time budget (minutes): {hours_budget_minutes:.0f}",
        f"Mode: {mode}",
        "Objectives with candidate sets (JSON):",
        json.dumps(objectives_payload, indent=2),
    ]
    if mode == "patch":
        parts.append("Existing plan items (JSON) -- patch/re-sequence these given the operators below:")
        parts.append(json.dumps(existing_items or [], indent=2))
        parts.append("Operators to apply (JSON, closed set from Reflection):")
        parts.append(json.dumps(operators or [], indent=2))
    if validation_feedback:
        parts.append("Your previous draft failed deterministic validation with these violations -- fix them:")
        parts.append("\n".join(f"- {v}" for v in validation_feedback))
    parts.append("Respond with ONLY the JSON object described in the system prompt.")
    return "\n\n".join(parts)


def parse_planner_response(
    raw_text: str, candidate_sets: dict[str, ObjectiveCandidateSet]
) -> tuple[list[PlanItemDraft], str]:
    """Strict parse + candidate-ID validation. Raises `PlannerParseError` on
    malformed JSON, a missing/unknown key, or any ID not present in
    `candidate_sets` -- ARCHITECTURE_CONTRACTS.md §7's "unknown IDs -> reject"
    applied at the earliest possible point, before a draft plan is ever
    handed to the deterministic Plan Validator.
    """
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise PlannerParseError(f"invalid JSON: {exc}") from exc

    if not isinstance(payload, dict) or "items" not in payload:
        raise PlannerParseError("response must be a JSON object with an 'items' array")

    raw_items = payload["items"]
    if not isinstance(raw_items, list):
        raise PlannerParseError("'items' must be a JSON array")

    drafts: list[PlanItemDraft] = []
    seen_ids: set[str] = set()
    for i, raw in enumerate(raw_items):
        if not isinstance(raw, dict):
            raise PlannerParseError(f"item {i} is not a JSON object")

        objective_id = raw.get("objective_id")
        cs = candidate_sets.get(objective_id)
        if cs is None:
            raise PlannerParseError(f"item {i}: unknown objective_id {objective_id!r}")

        item_type = raw.get("type")
        if item_type not in _VALID_TYPES:
            raise PlannerParseError(f"item {i}: invalid type {item_type!r}")

        skill_id = raw.get("skill_id")
        if skill_id != cs.skill_id:
            raise PlannerParseError(f"item {i}: skill_id {skill_id!r} does not match objective {objective_id!r}")

        resource_id = raw.get("resource_id")
        if resource_id is not None and resource_id not in {r.resource_id for r in cs.resources}:
            raise PlannerParseError(f"item {i}: resource_id {resource_id!r} not in objective's candidates")

        practice_item_ids = raw.get("practice_item_ids") or []
        if not isinstance(practice_item_ids, list) or any(
            p not in cs.practice_item_ids for p in practice_item_ids
        ):
            raise PlannerParseError(f"item {i}: practice_item_ids not all in objective's candidates")

        try:
            est_minutes = int(raw["est_minutes"])
            difficulty = int(raw["difficulty"])
            day_slot = int(raw["day_slot"])
        except (KeyError, TypeError, ValueError) as exc:
            raise PlannerParseError(f"item {i}: missing/invalid numeric field ({exc})") from exc

        item_id = raw.get("item_id") or str(uuid.uuid4())
        if item_id in seen_ids:
            item_id = str(uuid.uuid4())
        seen_ids.add(item_id)

        depends_on = raw.get("depends_on") or []
        if not isinstance(depends_on, list):
            raise PlannerParseError(f"item {i}: depends_on must be a list")

        drafts.append(
            PlanItemDraft(
                item_id=item_id,
                type=item_type,
                objective_id=objective_id,
                skill_id=skill_id,
                resource_id=resource_id,
                practice_item_ids=list(practice_item_ids),
                est_minutes=est_minutes,
                difficulty=difficulty,
                day_slot=day_slot,
                depends_on=list(depends_on),
                reason_text=str(raw.get("reason_text", "")),
            )
        )

    overall_reason = str(payload.get("overall_reason", ""))
    return drafts, overall_reason
