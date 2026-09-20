"""Intent classification and tool planning (design §9.6: "classify_intent
(small model or rule-based) -> plan_tools"; §23.1's question-type -> tools
table).

This project chooses the rule-based option. `LLM_PROVIDER=none` is this
project's permanent default (every other agent's module docstring makes the
same point), and design explicitly allows it here. Rule-based planning also
makes the Phase 10 brief's "maximum tool steps must be bounded" hold *by
construction* — a fixed, deterministic tool plan can never spiral into an
open-ended tool-calling loop the way an LLM choosing its own tool calls
turn-by-turn could (ARCHITECTURE_CONTRACTS.md P6's "tutor tool steps ≤ 4" is
a ceiling this module's every branch stays well under, not a runtime guard
against a loop that could otherwise happen).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.core.thresholds import TUTOR_MAX_TOOL_STEPS
from app.tutor.context import TutorContext

CURRENT_SKILLS = "current_skills"
GAPS = "gaps"
PLAN = "plan"
WHY_RECOMMENDED = "why_recommended"
WHY_CHANGED = "why_changed"
CONCEPT_EXPLANATION = "concept_explanation"
PROGRESS = "progress"
OUT_OF_SCOPE = "out_of_scope"

# design §23.1's example phrasings, mapped onto question-type keywords.
# Checked in this order — a message matching an earlier row wins (e.g. "why
# did my plan change" must win over the generic "plan" keyword in `PLAN`).
_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (WHY_CHANGED, ("plan change", "changed my plan", "what changed", "revision")),
    (PROGRESS, ("how am i doing", "my progress", "how far", "on track", "progress report")),
    (WHY_RECOMMENDED, ("why this resource", "why recommend", "why this video", "why this course", "why this item")),
    (GAPS, ("gap", "missing", "what am i missing", "still need", "why am i missing")),
    (CURRENT_SKILLS, ("evidence", "what do i know", "do i know", "proof i know", "my skills")),
    (PLAN, ("this week", "what should i do", "my plan", "schedule", "today's plan", "next up")),
)


@dataclass
class ToolCall:
    tool: str
    args: dict = field(default_factory=dict)


@dataclass
class Intent:
    name: str
    skill_id: str | None = None
    decision_id: str | None = None


async def _find_mentioned_skill_id(ctx: TutorContext, message: str) -> str | None:
    """Deterministic, catalog-anchored, **word-boundary** match against
    curated skill labels/aliases — the same approach
    `app/profiling/claim_extraction.py`'s `DeterministicClaimExtractor` uses
    for the same reasons: no LLM needed, a matched skill_id is always a real
    one (ARCHITECTURE_CONTRACTS.md §7), and a plain substring scan would
    false-positive on short aliases (e.g. the alias "mean" inside "meaning
    of life") the way `DeterministicClaimExtractor`'s own docstring already
    warns about."""
    skills = await ctx.catalog.get_all_skills()
    best: tuple[int, str] | None = None  # (matched length, skill_id) — longest match wins
    for s in skills:
        for candidate in (s.label, *(s.aliases or [])):
            candidate = (candidate or "").strip()
            if not candidate:
                continue
            pattern = r"(?<!\w)" + re.escape(candidate) + r"(?!\w)"
            if re.search(pattern, message, re.IGNORECASE) and (best is None or len(candidate) > best[0]):
                best = (len(candidate), s.skill_id)
    return best[1] if best else None


def _classify_keywords(message: str) -> str:
    lowered = message.lower()
    for intent_name, keywords in _KEYWORDS:
        if any(kw in lowered for kw in keywords):
            return intent_name
    return CONCEPT_EXPLANATION  # default bucket: "why do I need X" / general concept questions


async def classify_intent(
    ctx: TutorContext, message: str, *, skill_id_hint: str | None = None, decision_id_hint: str | None = None
) -> Intent:
    skill_id = skill_id_hint or await _find_mentioned_skill_id(ctx, message)
    name = _classify_keywords(message)
    if name == CONCEPT_EXPLANATION and skill_id is None and decision_id_hint is None:
        # Nothing groundable in the message at all — design §23.1's
        # "Out of scope -> Polite refusal or redirect".
        name = OUT_OF_SCOPE
    return Intent(name=name, skill_id=skill_id, decision_id=decision_id_hint)


def plan_tools(intent: Intent) -> list[ToolCall]:
    """design §23.1's question-type -> tools table. Every branch names at
    most 2 tools, well under `TUTOR_MAX_TOOL_STEPS`; the final slice is a
    defensive ceiling, never expected to actually trim anything."""
    calls: list[ToolCall] = []
    if intent.name == CURRENT_SKILLS:
        calls.append(ToolCall("get_learner_state"))
        if intent.skill_id:
            calls.append(ToolCall("get_evidence", {"skill_id": intent.skill_id}))
    elif intent.name == GAPS:
        calls.append(ToolCall("get_gaps"))
        if intent.skill_id:
            calls.append(ToolCall("explain_skill_path", {"skill_id": intent.skill_id}))
    elif intent.name == PLAN:
        calls.append(ToolCall("get_current_plan"))
    elif intent.name == WHY_RECOMMENDED:
        if intent.decision_id:
            calls.append(ToolCall("get_decision", {"decision_id": intent.decision_id}))
        calls.append(ToolCall("get_current_plan"))
    elif intent.name == WHY_CHANGED:
        calls.append(ToolCall("get_revisions"))
        if intent.decision_id:
            calls.append(ToolCall("get_decision", {"decision_id": intent.decision_id}))
    elif intent.name == CONCEPT_EXPLANATION and intent.skill_id:
        calls.append(ToolCall("explain_skill_path", {"skill_id": intent.skill_id}))
        calls.append(ToolCall("search_resources", {"skill_id": intent.skill_id}))
    elif intent.name == PROGRESS:
        calls.append(ToolCall("get_progress"))
    # OUT_OF_SCOPE (or a CONCEPT_EXPLANATION with nothing to ground it, which
    # `classify_intent` already downgrades to OUT_OF_SCOPE) -> no tool calls;
    # the service layer short-circuits straight to a scripted refusal.
    return calls[:TUTOR_MAX_TOOL_STEPS]
