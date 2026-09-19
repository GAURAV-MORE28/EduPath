"""Evidence bundle assembly (design §20.3): everything the Reflection Agent
(and the deterministic policy that stands in for it while
`LLM_PROVIDER=none`, this project's permanent default) needs to diagnose a
root cause and choose operators, plus everything the Reflection Validator
needs to check that evidence actually supports the struggle signal.

A plain dataclass built by `app/reflection/service.py` from data the caller
(`app/assessment/service.py`) already has in hand -- no DB/gateway import
here, same "pure assembly" shape `app/planning/candidates.py` uses for
`ObjectiveCandidateSet` (that one is async because it fetches resources;
this one takes already-fetched pieces so it stays synchronous and
trivially testable).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.assessment.struggle import StruggleSignalEntry
from app.schemas.common import PlanItem


@dataclass(frozen=True)
class EvidenceBundle:
    learner_id: str
    struggling_skill_id: str
    triggering_signal: StruggleSignalEntry
    all_signals: list[StruggleSignalEntry] = field(default_factory=list)
    misconception_id: str | None = None
    misconception_root_skill_id: str | None = None
    ancestor_statuses: dict[str, str] = field(default_factory=dict)  # hard ancestors of struggling_skill_id -> gap status
    graph_version: str = ""
    current_plan_items: list[PlanItem] = field(default_factory=list)
    learner_assessment_item_ids: frozenset[str] = field(default_factory=frozenset)  # design §20.6 check 2's "belongs to this learner"
    weekly_hours_budget_minutes: float = 0.0

    @property
    def prerequisite_gap_skill_id(self) -> str | None:
        """The `missing_prerequisite` signal's named prerequisite, if that
        class is among `all_signals` for this same struggling skill --
        surfaced regardless of which signal is `triggering_signal`, since
        the wow-scenario combo (repeated_misconception *and*
        missing_prerequisite firing on the same submission) needs both."""
        for s in self.all_signals:
            if s.signal_class == "missing_prerequisite" and s.skill_id == self.struggling_skill_id:
                return s.counts.get("prerequisite_skill_id")
        return None
