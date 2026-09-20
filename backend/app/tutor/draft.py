"""Shared `TutorDraft` shape — the Tutor Agent's parsed (but not yet
citation-verified) output. Its own small module for the same reason
`app/reflection/draft.py` has one: both the agent's parser and the service
orchestration layer need this shape without importing each other."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TutorDraft:
    answer: str
    citations: list[str] = field(default_factory=list)
