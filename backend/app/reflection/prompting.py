"""Reflection Agent (A4, mode b) prompt construction and response parsing
(design §8.2, §20.4). Mirrors `app/planning/prompting.py`'s split: a system
prompt describing the closed operator vocabulary, a builder that serializes
the evidence bundle plus a deterministically pre-resolved candidate ID set
into the user prompt, and a parser that validates the LLM's JSON strictly
against that candidate set before anything downstream sees it
(ARCHITECTURE_CONTRACTS.md §7).

Root-cause *identification* is deliberately not left to the LLM (see
`app/reflection/deterministic.py`'s module docstring) -- it is handed a
graph-identified candidate root cause (the struggling skill or a named hard
ancestor) plus pre-resolved remediation-resource and probe-item IDs, and is
asked to confirm or refine the *operators* and write the narrative fields
(hypothesis/critique/learner_explanation_draft/confidence/path_decision).
This keeps the one thing genuinely unsafe to hand an LLM (inventing a graph
node or a resource ID) structurally impossible, matching how
`app/planning/prompting.py` already treats resource/practice IDs.
"""
from __future__ import annotations

import json
from typing import Any

from app.reflection.draft import ReflectionDraft
from app.reflection.evidence import EvidenceBundle
from app.reflection.operators import CLOSED_OPERATOR_SET

REFLECTION_SYSTEM_PROMPT = """You are the Reflection module for EduPath, an adaptive learning-path system.
A learner is struggling on a skill. You will be given: the struggling skill, the classifier's
struggle signal (class, confidence, evidence item IDs), a graph-identified candidate root-cause
skill (either the struggling skill itself or one of its curated hard-prerequisite ancestors),
candidate remediation resource IDs, and candidate probe/practice item IDs -- all already resolved
for you. You may NEVER invent a skill_id, resource_id, or practice_item_id that was not given to you.

You choose operators ONLY from this closed set:
  INSERT_REMEDIATION {skill_id, resource_ids[], mode}
  DEFER {skill_id or item_ids[], delay_days?}
  REMOVE_DUPLICATE {item_ids[]}
  REPLACE_RESOURCE {item_id, new_resource_id}
  ADD_PROBE {skill_id, purpose, practice_item_ids[]}
  SPLIT_ACTIVITY {item_id, parts?}

Output ONLY a JSON object with this exact shape:
{
  "root_cause_class": "<the given signal class>",
  "root_cause_skill_id": "<the given root-cause skill_id, or the struggling skill_id>",
  "misconception_id": "<the given misconception_id, or null>",
  "evidence_ids": ["<subset of the given evidence item IDs -- must be non-empty>"],
  "hypothesis": "<one sentence: what you believe is going wrong and why>",
  "confidence": "low" | "medium" | "high",
  "path_decision": "keep" | "patch" | "rebuild_from",
  "operators": [ {"op": "<one of the closed set>", "params": {...}} ],
  "critique": "<one short sentence, optional>",
  "learner_explanation_draft": "<one short learner-facing paragraph explaining the change>"
}

Output ONLY the JSON object. No prose, no markdown fences."""


class ReflectionParseError(Exception):
    pass


def build_reflection_prompt(
    bundle: EvidenceBundle,
    *,
    candidate_root_cause_skill_ids: list[str],
    candidate_resource_ids: list[str],
    candidate_probe_item_ids: list[str],
    validation_feedback: list[str] | None = None,
) -> str:
    signal = bundle.triggering_signal
    payload = {
        "struggling_skill_id": bundle.struggling_skill_id,
        "signal_class": signal.signal_class,
        "signal_confidence": signal.confidence,
        "signal_evidence_ids": list(signal.evidence_ids),
        "signal_counts": signal.counts,
        "misconception_id": bundle.misconception_id,
        "ancestor_statuses": bundle.ancestor_statuses,
        "candidate_root_cause_skill_ids": candidate_root_cause_skill_ids,
        "candidate_resource_ids": candidate_resource_ids,
        "candidate_probe_item_ids": candidate_probe_item_ids,
        "learner_assessment_item_ids": sorted(bundle.learner_assessment_item_ids),
        "weekly_hours_budget_minutes": bundle.weekly_hours_budget_minutes,
    }
    parts = ["Evidence bundle (JSON):", json.dumps(payload, indent=2)]
    if validation_feedback:
        parts.append("Your previous response failed deterministic validation with these reasons -- fix them:")
        parts.append("\n".join(f"- {r}" for r in validation_feedback))
    parts.append("Respond with ONLY the JSON object described in the system prompt.")
    return "\n\n".join(parts)


def parse_reflection_response(
    raw_text: str,
    bundle: EvidenceBundle,
    *,
    candidate_root_cause_skill_ids: list[str],
    candidate_resource_ids: list[str],
    candidate_probe_item_ids: list[str],
) -> ReflectionDraft:
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ReflectionParseError(f"invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ReflectionParseError("response must be a JSON object")

    root_cause_skill_id = payload.get("root_cause_skill_id")
    if root_cause_skill_id not in candidate_root_cause_skill_ids:
        raise ReflectionParseError(f"root_cause_skill_id {root_cause_skill_id!r} not among the given candidates")

    misconception_id = payload.get("misconception_id")
    if misconception_id is not None and misconception_id != bundle.misconception_id:
        raise ReflectionParseError(f"misconception_id {misconception_id!r} does not match the given one")

    evidence_ids = payload.get("evidence_ids")
    if not isinstance(evidence_ids, list) or not evidence_ids:
        raise ReflectionParseError("evidence_ids must be a non-empty array")
    unknown = [e for e in evidence_ids if e not in bundle.learner_assessment_item_ids]
    if unknown:
        raise ReflectionParseError(f"evidence_ids not in this learner's assessment history: {unknown}")

    confidence = payload.get("confidence")
    if confidence not in ("low", "medium", "high"):
        raise ReflectionParseError(f"invalid confidence {confidence!r}")

    path_decision = payload.get("path_decision")
    if path_decision not in ("keep", "patch", "rebuild_from"):
        raise ReflectionParseError(f"invalid path_decision {path_decision!r}")

    operators = payload.get("operators")
    if not isinstance(operators, list):
        raise ReflectionParseError("operators must be an array")
    allowed_resource_ids = set(candidate_resource_ids)
    allowed_probe_ids = set(candidate_probe_item_ids)
    allowed_skill_ids = set(candidate_root_cause_skill_ids) | {bundle.struggling_skill_id}
    for i, operator in enumerate(operators):
        if not isinstance(operator, dict) or operator.get("op") not in CLOSED_OPERATOR_SET:
            raise ReflectionParseError(f"operator {i}: not in the closed set")
        params: dict[str, Any] = operator.get("params") or {}
        skill_id = params.get("skill_id")
        if skill_id is not None and skill_id not in allowed_skill_ids:
            raise ReflectionParseError(f"operator {i}: skill_id {skill_id!r} not among the given candidates")
        for rid in params.get("resource_ids") or []:
            if rid not in allowed_resource_ids:
                raise ReflectionParseError(f"operator {i}: resource_id {rid!r} not among the given candidates")
        new_resource_id = params.get("new_resource_id")
        if new_resource_id is not None and new_resource_id not in allowed_resource_ids:
            raise ReflectionParseError(f"operator {i}: new_resource_id {new_resource_id!r} not among the given candidates")
        for pid in params.get("practice_item_ids") or []:
            if pid not in allowed_probe_ids:
                raise ReflectionParseError(f"operator {i}: practice_item_id {pid!r} not among the given candidates")

    return ReflectionDraft(
        root_cause_class=str(payload.get("root_cause_class", bundle.triggering_signal.signal_class)),
        root_cause_skill_id=root_cause_skill_id,
        misconception_id=misconception_id,
        evidence_ids=list(evidence_ids),
        hypothesis=str(payload.get("hypothesis", "")),
        confidence=confidence,
        path_decision=path_decision,
        operators=operators,
        critique=str(payload.get("critique", "")),
        learner_explanation_draft=str(payload.get("learner_explanation_draft", "")),
    )
