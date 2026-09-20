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

from app.core.thresholds import PLAN_TARGET_UTILIZATION
from app.planning.candidates import ObjectiveCandidateSet
from app.planning.sessions import session_meta

PLANNER_SYSTEM_PROMPT = """You are the Planner for EduPath, an adaptive learning-path system.
You will be given a weekly time budget (minutes) and a list of learning objectives, each with a
pre-built candidate set: eligible resource IDs (already ranked, already filtered for eligibility)
and practice/probe item IDs. You must select and sequence items ONLY from these candidate IDs --
you may never invent a resource_id, session_id, practice_item_id, objective_id, or skill_id.
A long resource is offered as several study sessions (session_id "<resource_id>#<n>", n = 1..sessions);
you choose which sessions to schedule, code fixes each session's minutes.

Output ONLY a JSON object with this exact shape:
{
  "items": [
    {
      "type": "resource" | "practice" | "probe" | "project" | "review",
      "objective_id": "<one of the given objective_ids>",
      "skill_id": "<the objective's skill_id>",
      "resource_id": "<a resource_id from that objective's candidates, or null>",
      "session_id": "<'<resource_id>#<n>' for a resource item, or null>",
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
- A "resource" item must use a resource_id from that objective's candidates and the session_id of ONE of its sessions
  ("<resource_id>#<n>"). To study several sessions of a resource, emit one item per session, in ascending n starting at the
  lowest offered n, with non-decreasing day_slot. Never skip a session and never repeat one.
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
    # Stage 2: the real study session (`app.planning.sessions.SessionMeta` as a dict) a resource item was resolved to.
    session: dict | None = None


_VALID_TYPES = {"resource", "practice", "probe", "project", "review"}


def _resource_payload(r) -> dict:
    """Compact on purpose (Groq's free tier is ~8K tokens/min): a session list is described as a count plus its minutes, never
    spelled out id by id -- the parser validates every id the model produces against the real session table."""
    minutes = [s.est_minutes for s in r.sessions]
    payload = {"resource_id": r.resource_id, "title": r.title, "type": r.type, "modality": r.modality}
    if len(minutes) == 1:
        payload["sessions"] = 1
        payload["minutes"] = minutes[0]
    else:
        payload["sessions"] = len(minutes)
        payload["first_n"] = r.sessions[0].index  # earlier sessions may already be done
        payload["minutes_each"] = f"{min(minutes)}-{max(minutes)}" if min(minutes) != max(minutes) else str(minutes[0])
        payload["total_min"] = sum(minutes)
    return payload


def build_planner_prompt(
    *,
    candidate_sets: dict[str, ObjectiveCandidateSet],
    hours_budget_minutes: float,
    mode: str,
    existing_items: list[dict] | None = None,
    operators: list[dict] | None = None,
    validation_feedback: list[str] | None = None,
    new_skill_cap: int | None = None,
    unmet_prerequisites: dict[str, list[str]] | None = None,
) -> str:
    unmet_prerequisites = unmet_prerequisites or {}
    objective_skills = {cs.skill_id for cs in candidate_sets.values()}
    objectives_payload = [
        {
            "objective_id": cs.objective_id,
            "skill_id": cs.skill_id,
            "objective_type": cs.objective_type,
            "target_level": cs.target_level,
            "current_level": cs.current_level,
            "max_item_difficulty": cs.current_level + 1,
            "unmet_hard_prerequisite_skills": unmet_prerequisites.get(cs.skill_id, []),
            "schedulable_this_week": all(p in objective_skills for p in unmet_prerequisites.get(cs.skill_id, [])),
            "priority": round(cs.priority, 3),
            "candidate_resources": [_resource_payload(r) for r in cs.resources],
            "candidate_practice_item_ids": cs.practice_item_ids,
        }
        for cs in sorted(candidate_sets.values(), key=lambda c: -c.priority)
    ]

    cap_line = (
        f"1. At most {new_skill_cap} DISTINCT skill_ids may appear in resource/practice/review/project items "
        "(probe items do not count). Pick the highest-priority objectives and drop the rest.\n"
        if new_skill_cap
        else ""
    )
    constraints = (
        "HARD CONSTRAINTS -- checked by code; a draft that breaks any of them is thrown away:\n"
        + cap_line
        + "2. Never schedule an objective whose schedulable_this_week is false. If an objective lists "
        "unmet_hard_prerequisite_skills, EVERY one of those skills must have an item on a STRICTLY EARLIER day_slot; "
        "if that is not possible, leave the objective out.\n"
        "3. Every item's difficulty must be <= its objective's max_item_difficulty.\n"
        "4. Sum of est_minutes must be <= the weekly budget; a session's est_minutes is its own length (minutes / minutes_each).\n"
        "5. Use each session_id at most once (a single-session resource: each resource_id at most once).\n"
        "6. Use the budget well: aim for roughly "
        f"{round(PLAN_TARGET_UTILIZATION * 100)}% of it ({round(PLAN_TARGET_UTILIZATION * hours_budget_minutes)} min) with the "
        "highest-value material for the objectives you keep -- more sessions of a long resource, then the next-ranked resource "
        "for the same objective -- but never pad with unrelated material and never exceed the hard limits above. Keep reason_text "
        "under 15 words."
    )
    parts = [
        f"Weekly time budget (minutes): {hours_budget_minutes:.0f}",
        f"Mode: {mode}",
        constraints,
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
        session_id = raw.get("session_id")
        session = None
        if session_id is not None:
            # The session id is authoritative: it must be one this objective really offers, and it fixes the resource.
            session = cs.sessions_by_id().get(session_id)
            if session is None:
                raise PlannerParseError(f"item {i}: session_id {session_id!r} not in objective's candidates")
            if resource_id is not None and resource_id != session.resource_id:
                raise PlannerParseError(f"item {i}: session_id {session_id!r} does not belong to resource_id {resource_id!r}")
            resource_id = session.resource_id
        elif resource_id is not None:
            res = cs.resource(resource_id)
            if res is None:
                raise PlannerParseError(f"item {i}: resource_id {resource_id!r} not in objective's candidates")
            if len(res.sessions) != 1:
                raise PlannerParseError(
                    f"item {i}: resource {resource_id!r} has {len(res.sessions)} sessions; give a session_id ('{resource_id}#<n>')"
                )
            session = res.sessions[0]  # a complete short resource: its only session is unambiguous

        practice_item_ids = raw.get("practice_item_ids") or []
        if not isinstance(practice_item_ids, list) or any(
            p not in cs.practice_item_ids for p in practice_item_ids
        ):
            raise PlannerParseError(f"item {i}: practice_item_ids not all in objective's candidates")

        try:
            est_minutes = int(raw["est_minutes"]) if session is None else session.est_minutes
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
                session=session_meta(session).__dict__ if session is not None else None,
            )
        )

    overall_reason = str(payload.get("overall_reason", ""))
    return drafts, overall_reason
