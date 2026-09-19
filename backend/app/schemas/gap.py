"""Gap Engine API response shapes (design §13, §25.2, §27's `GET
/api/learners/me/gaps`).

`SkillGap`/`LearningObjective` are the core §25.2 schema names and live in
`app/schemas/common.py`; everything else here is supporting shape specific to
this endpoint's response (not one of ARCHITECTURE_CONTRACTS.md §6's twelve
core schema names, but additive, same latitude Phase 2/3 already used for
e.g. `RunClaimsSummary`/`GraphMeta`).
"""
from __future__ import annotations

from pydantic import BaseModel

from app.schemas.common import LearningObjective, SkillGap


class Strength(BaseModel):
    """design §13.1's `strengths[]` — the evidence-backed `MET` subset of
    `gaps`, repeated here in a smaller shape for a UI that only wants to
    render "what you already have"."""

    skill_id: str
    label: str
    required_level: int
    current_level: int
    tier_max: str
    mastery: float
    evidence_ids: list[str] = []


class AuditFlag(BaseModel):
    """design §12.4. The per-skill `flag_type`s also appear inline on the
    matching `SkillGap.audit_flags`; this is the flat list with the
    human-readable `message` and any `related_skill_ids` (e.g. the PART_OF
    children behind a `claim_evidence_mismatch`)."""

    flag_type: str
    skill_id: str
    message: str
    related_skill_ids: list[str] = []


class GapGraphEdge(BaseModel):
    """One hard `PREREQUISITE_OF` edge with both endpoints in the target-role
    subgraph — enough for the frontend to draw the gap graph (Phase 5
    brief's UI requirement) without re-deriving it from raw skill edges."""

    from_skill_id: str
    to_skill_id: str


class GapReport(BaseModel):
    """`GET /api/learners/me/gaps` response body (design §27 table)."""

    role_id: str
    graph_version: str
    gaps: list[SkillGap]
    strengths: list[Strength]
    audit_flags: list[AuditFlag]
    objectives: list[LearningObjective]
    layers: list[list[str]]  # topological ordering layers over non-MET scope skills, for UI sequencing
    prerequisite_edges: list[GapGraphEdge]
