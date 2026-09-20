"""Tutor / Provenance API shapes (design §27: `POST /api/learners/me/chat`,
`GET /api/decisions/{id}`). `ProgressReport` (the core §25.2 schema name)
lives in `app/schemas/common.py`; everything here is request/response shape
specific to these two endpoints -- same split `app/schemas/gap.py`/
`app/schemas/planning.py`/`app/schemas/assessment.py` already use.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ChatRequest(BaseModel):
    """design §27's `{message}`. `skill_id_hint`/`decision_id_hint` are this
    project's addition beyond that literal shape -- a real UI's "Why?" drawer
    (design §24.3) already knows the exact skill/decision it is asking
    about; free-text-only extraction is a fallback, not the only path
    (`app/tutor/intent.py`)."""

    message: str
    skill_id_hint: str | None = None
    decision_id_hint: str | None = None


class ChatResponse(BaseModel):
    """design §27: "Streamed answer with citations." Not actually streamed
    this phase (see `app/api/v1/tutor.py`'s module docstring for why) -- the
    same complete answer a stream would have ended with, returned as one
    JSON body."""

    answer: str
    citations: list[str] = []
    degraded: bool = False  # true once the conservative (non-LLM) answer was used
    conservative: bool = False


class DecisionRecordOut(BaseModel):
    """design §24.1's `DecisionRecord`, resolved for `GET /api/decisions/{id}`."""

    decision_id: str
    learner_id: str
    type: str
    inputs: dict[str, Any] = {}
    evidence_ids: list[str] = []
    graph_paths: list[list[str]] = []
    rules_fired: list[str] = []
    scores: dict[str, Any] = {}
    graph_version: str = ""
    output_ref: str = ""
