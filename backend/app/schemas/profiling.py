"""Learner Profiling + Evidence Pipeline schemas (design §22.3, §25.2, §27).

`ExtractedClaim` is the Profiler Agent's *only* output shape
(ARCHITECTURE_CONTRACTS.md §2: "Profiler ... emits ExtractedClaims only").
Everything downstream (`VerifiedClaim`, `NormalizedClaim`) adds fields as the
deterministic pipeline stages (Evidence Verifier, Skill Normalizer) process
it — the claim itself is never mutated in place, so each stage's input is
always traceable back to exactly what the Profiler produced.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ContextType = Literal["skills_list", "project", "experience", "education", "certificate"]
EvidenceTier = Literal["E0", "E1", "E2", "E3"]
NormalizationMethod = Literal["exact_alias", "embedding", "llm_disambiguation", "unmapped"]


class SpanOffsets(BaseModel):
    start: int
    end: int


class ExtractedClaim(BaseModel):
    """design §22.3. Every claim must carry a verbatim span into the source
    document text — "no span means no evidence" (§22.5)."""

    label: str
    category: str = ""
    context_type: ContextType
    claimed_level_cue: str | None = None
    verbatim_span: str
    source_doc_id: str
    span_offsets: SpanOffsets


class VerifiedClaim(BaseModel):
    """`ExtractedClaim` + the Evidence Verifier's deterministic outcome
    (design §22.4/§22.5): the span was fuzzy-matched against the source text,
    a tier was assigned, and the injection detector ran."""

    claim: ExtractedClaim
    tier: EvidenceTier
    span_verified: bool
    injection_flagged: bool
    injection_matches: list[str] = Field(default_factory=list)


class NormalizedClaim(BaseModel):
    """`VerifiedClaim` + the Skill Normalizer's resolution (design §22.1
    pipeline stage 6): `skill_id` is `None` exactly when `method ==
    "unmapped"` — an unmapped label is retained as free text, never
    force-fit onto a graph node (§22.5 point 4)."""

    verified: VerifiedClaim
    skill_id: str | None
    method: NormalizationMethod
    confidence: float


class RunClaimsSummary(BaseModel):
    """Returned alongside a document-upload/G1 run: what happened to every
    claim the Profiler proposed, including the ones that never made it to a
    `PendingClaim` row."""

    run_id: str
    extracted: int
    dropped_unverified: int
    dropped_injection: int
    pending: int
    degraded: bool = False


# -- Intake (design §27 POST /api/learners) ---------------------------------


class IntakePreferences(BaseModel):
    modality_order: list[Literal["watch", "read", "do"]] = Field(default_factory=lambda: ["do", "read", "watch"])
    language: str = "en"
    session_length_min: int | None = None


class IntakeRequest(BaseModel):
    current_skills: list[str] = Field(default_factory=list)  # self-reported skill labels -> E0 claims
    experience_summary: str = ""
    target_role_id: str
    career_goal: str = ""
    weekly_hours: float = Field(gt=0, le=80)
    preferences: IntakePreferences = Field(default_factory=IntakePreferences)
    constraints: dict = Field(default_factory=dict)


class UnmappedSkill(BaseModel):
    label: str
    reason: str


class LearnerProfileOut(BaseModel):
    learner_id: str
    target_role_id: str
    career_goal: str
    experience_summary: str
    weekly_hours: float
    preferences: dict
    constraints: dict
    mapped_skill_count: int
    unmapped_skills: list[UnmappedSkill] = Field(default_factory=list)


# -- Documents ----------------------------------------------------------------


class DocumentUploadResponse(BaseModel):
    document_id: str
    run_id: str
    parse_status: str
    claims_summary: RunClaimsSummary


class GitHubUploadRequest(BaseModel):
    repo_url: str


# -- Pending claims / confirmation --------------------------------------------


class PendingClaimOut(BaseModel):
    claim_id: str
    skill_label: str
    category: str
    context_type: str
    claimed_level_cue: str | None
    verbatim_span: str
    span_offsets: SpanOffsets
    tier: str
    document_id: str | None
    normalized_skill_id: str | None
    normalization_method: str
    normalization_confidence: float


class ClaimDecision(BaseModel):
    claim_id: str
    action: Literal["confirm", "remove", "edit"]
    # Only used with action="edit" or to manually map an "unmapped" claim before confirming.
    skill_id_override: str | None = None


class ClaimConfirmationInput(BaseModel):
    decisions: list[ClaimDecision]


class ConfirmationSummary(BaseModel):
    confirmed: int
    removed: int
    skipped_no_skill: int  # confirmed but no skill_id resolved (not manually mapped) -> not committed
    evidence_created: list[str]  # evidence_id[]


# -- GitHub ---------------------------------------------------------------------


class GitHubRepoSummary(BaseModel):
    """design §26.2 `github_repo_summary` tool output. Metadata only — no
    deep code analysis (explicitly out of scope this phase)."""

    repo_url: str
    full_name: str
    description: str = ""
    languages: dict[str, int] = Field(default_factory=dict)  # language -> byte count, from GitHub's API
    readme_excerpt: str = ""
    manifest_files: list[str] = Field(default_factory=list)  # e.g. requirements.txt, package.json
    top_level_files: list[str] = Field(default_factory=list)
    fetched: bool
    degraded_reason: str | None = None
