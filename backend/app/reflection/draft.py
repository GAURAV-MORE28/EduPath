"""`ReflectionDraft` -- the framework-independent shape both the
deterministic policy (`app/reflection/deterministic.py`) and the LLM agent's
parsed response (`app/reflection/prompting.py`) produce, mirroring design
§20.4's `ReflectionResult` shape (before it is validated and, if approved,
persisted as the real `ReflectionRecord`/`PlanRevision`).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ReflectionDraft:
    root_cause_class: str
    root_cause_skill_id: str
    misconception_id: str | None
    evidence_ids: list[str]
    hypothesis: str
    confidence: str  # low | medium | high
    path_decision: str  # keep | patch | rebuild_from
    operators: list[dict[str, Any]] = field(default_factory=list)
    critique: str = ""
    learner_explanation_draft: str = ""
