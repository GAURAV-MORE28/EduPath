"""The deterministic root-cause policy and operator-skeleton builder.

This is what actually runs end to end in this environment: `LLM_PROVIDER=none`
is this project's permanent default (every prior phase's Agent gateway call
degrades deterministically, see `app/gateway/llm_gateway.py`), so the "real"
Reflection Agent LLM path (`app/agents/reflection.py`) is exercised only via
a scripted stub gateway in tests -- exactly the same situation the Planner
Agent (Phase 5) and Profiler Agent (Phase 2) were already in, each of which
answered it the same way: a deterministic policy that the *service* falls
back to, not a special "fallback node" the agent hides inside itself.

design §20.6's "deterministic patch" recipe -- "insert remediation for the
root skill from REMEDIATED_BY or top-ranked prerequisite resources; defer
dependents; drop lowest-priority items to fit the budget" -- generalized
here across all four of design §20.2's reflection-triggering classes
(misconception_confirmed, prerequisite_gap, difficulty_mismatch, overload),
mapped onto this project's `app.assessment.struggle` class names.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.assessment.struggle import (
    COGNITIVE_OVERLOAD,
    EXCESSIVE_DIFFICULTY,
    MISSING_PREREQUISITE,
    REPEATED_MISCONCEPTION,
)
from app.reflection.draft import ReflectionDraft
from app.reflection.evidence import EvidenceBundle
from app.reflection.operators import OP_ADD_PROBE, OP_DEFER, OP_INSERT_REMEDIATION, OP_SPLIT_ACTIVITY


@dataclass(frozen=True)
class RootCauseDecision:
    skill_id: str
    root_cause_class: str
    misconception_id: str | None
    confidence: str
    evidence_ids: list[str]
    hypothesis: str


def deterministic_root_cause(bundle: EvidenceBundle) -> RootCauseDecision:
    """Pure function: no DB/graph access, uses only what's already resolved
    onto `bundle`. Root cause identification itself never needs an LLM here
    -- it is either read straight off the struggle signal
    (`missing_prerequisite`'s named prerequisite) or off the curated graph
    (a confirmed misconception's `ROOTED_IN` skill, already resolved onto
    `bundle.misconception_root_skill_id` by the caller) -- consistent with
    ARCHITECTURE_CONTRACTS.md §7 ("an LLM never invents an ID") and design
    §20.6 point 3 ("on conflict the classifier wins").
    """
    signal = bundle.triggering_signal
    struggling = bundle.struggling_skill_id

    if signal.signal_class == REPEATED_MISCONCEPTION:
        # Prefer an explicit co-occurring missing_prerequisite signal's
        # named prerequisite (the wow scenario: chain_rule) over the
        # misconception's own ROOTED_IN skill, when both are present and
        # differ -- the more specific, evidence-attributed signal wins.
        prereq = bundle.prerequisite_gap_skill_id
        root_skill_id = prereq or bundle.misconception_root_skill_id or struggling
        evidence_ids = list(signal.evidence_ids)
        return RootCauseDecision(
            skill_id=root_skill_id,
            root_cause_class=signal.signal_class,
            misconception_id=bundle.misconception_id,
            confidence=signal.confidence,
            evidence_ids=evidence_ids,
            hypothesis=(
                f"Repeated wrong answers on {struggling} carry the {bundle.misconception_id} misconception, "
                f"rooted in {root_skill_id}."
            ),
        )

    if signal.signal_class == MISSING_PREREQUISITE:
        root_skill_id = signal.counts.get("prerequisite_skill_id", struggling)
        return RootCauseDecision(
            skill_id=root_skill_id,
            root_cause_class=signal.signal_class,
            misconception_id=None,
            confidence=signal.confidence,
            evidence_ids=list(signal.evidence_ids),
            hypothesis=f"{struggling} failures are attributable to an unmet prerequisite, {root_skill_id}.",
        )

    if signal.signal_class == EXCESSIVE_DIFFICULTY:
        return RootCauseDecision(
            skill_id=struggling,
            root_cause_class=signal.signal_class,
            misconception_id=None,
            confidence=signal.confidence,
            evidence_ids=list(signal.evidence_ids),
            hypothesis=f"Items above {struggling}'s current level are failing -- the step size is too large.",
        )

    if signal.signal_class == COGNITIVE_OVERLOAD:
        return RootCauseDecision(
            skill_id=struggling,
            root_cause_class=signal.signal_class,
            misconception_id=None,
            confidence=signal.confidence,
            evidence_ids=list(signal.evidence_ids),
            hypothesis="Multiple corroborating overload signals this week -- reduce load rather than push forward.",
        )

    # Defensive default -- design §20.2's trigger set is exactly the four
    # classes above; a caller should never route anything else here.
    return RootCauseDecision(
        skill_id=struggling,
        root_cause_class=signal.signal_class,
        misconception_id=bundle.misconception_id,
        confidence=signal.confidence,
        evidence_ids=list(signal.evidence_ids),
        hypothesis=f"Struggle detected on {struggling}.",
    )


def build_deterministic_draft(
    bundle: EvidenceBundle,
    root_cause: RootCauseDecision,
    *,
    remediation_resource_ids: list[str],
    probe_practice_item_ids: list[str],
    split_item_id: str | None = None,
) -> ReflectionDraft:
    """Builds the operator skeleton for `root_cause`. `remediation_resource_ids`
    and `probe_practice_item_ids` are pre-resolved by the caller (needs
    graph/DB access this pure function deliberately doesn't have) --
    `app/reflection/service.py`. `split_item_id`, when given, is the
    existing plan item `SPLIT_ACTIVITY` should chunk (the caller finds the
    longest current item for `bundle.struggling_skill_id`, if any).
    """
    struggling = bundle.struggling_skill_id
    root = root_cause.skill_id
    operators: list[dict] = []

    if root_cause.root_cause_class in (REPEATED_MISCONCEPTION, MISSING_PREREQUISITE):
        if root != struggling:
            operators.append({"op": OP_DEFER, "params": {"skill_id": struggling}})
        operators.append(
            {"op": OP_INSERT_REMEDIATION, "params": {"skill_id": root, "resource_ids": remediation_resource_ids[:1], "mode": "guided"}}
        )
        operators.append(
            {"op": OP_ADD_PROBE, "params": {"skill_id": root, "purpose": "resolution-check", "practice_item_ids": probe_practice_item_ids}}
        )
        path_decision = "patch"
        learner_explanation = (
            f"We noticed repeated trouble with {struggling}, traced back to {root}. "
            f"We've added a short remediation on {root} and moved {struggling}'s remaining items "
            "back a couple of days so you can shore that up first, with a quick check-in afterwards."
            if root != struggling
            else f"We noticed repeated trouble with {root} itself, so we've added a short remediation "
            "and a follow-up check on the same skill."
        )
    elif root_cause.root_cause_class == EXCESSIVE_DIFFICULTY:
        if split_item_id is not None:
            operators.append({"op": OP_SPLIT_ACTIVITY, "params": {"item_id": split_item_id, "parts": 2}})
        operators.append({"op": OP_DEFER, "params": {"skill_id": struggling, "delay_days": 1}})
        if probe_practice_item_ids:
            operators.append(
                {"op": OP_ADD_PROBE, "params": {"skill_id": root, "purpose": "verification", "practice_item_ids": probe_practice_item_ids}}
            )
        path_decision = "patch"
        learner_explanation = (
            f"The last few {struggling} items were above your current level. We've broken the next "
            "session into smaller steps and given it a bit more room this week."
        )
    else:  # COGNITIVE_OVERLOAD
        operators.append({"op": OP_DEFER, "params": {"skill_id": struggling, "delay_days": 3}})
        path_decision = "patch"
        learner_explanation = (
            f"This week looks overloaded, so we've pushed some of {struggling}'s remaining items out "
            "to give you more breathing room."
        )

    return ReflectionDraft(
        root_cause_class=root_cause.root_cause_class,
        root_cause_skill_id=root,
        misconception_id=root_cause.misconception_id,
        evidence_ids=root_cause.evidence_ids,
        hypothesis=root_cause.hypothesis,
        confidence=root_cause.confidence,
        path_decision=path_decision,
        operators=operators,
        critique="",
        learner_explanation_draft=learner_explanation,
    )
