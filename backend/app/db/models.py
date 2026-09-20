"""ORM models.

Phase 1 added only what was needed to prove the migration framework and
session-boundary work (design §28: `User`). Phase 3 (this file, remaining
classes below) adds the curated Skill Graph / catalog tables from
ARCHITECTURE_CONTRACTS.md §5/§9 and design §11.2-§11.3/§15.1/§28: `Skill`,
`SkillEdge`, `Role`, `RoleRequirement`, `Misconception`, `Resource`,
`ResourceSkill`, `PracticeItem`, plus `GraphMeta` (graph-versioning history —
not in design §28's conceptual list, but required by ARCHITECTURE_CONTRACTS.md
§5's "graph is versioned" and §14's "record graph_version in every
DecisionRecord"; see docs/ARCHITECTURE_CONTRACTS.md Contract Changes).

List-valued columns (`aliases`, `remediation_candidates`,
`prerequisite_skill_ids`, `options`) use the generic `JSON` type (as Phase 1
did for `consent_flags`) rather than `postgresql.ARRAY`/`JSONB`, so the same
model works against both Postgres (prod) and SQLite (tests) — the project's
existing dialect-portability convention (see `tests/conftest.py`).
Every other table in the conceptual schema not yet needed
(`LearnerProfile`, `Document`, `Evidence`, ...) is added by the phase that
owns it.
"""
import uuid
from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# Embedding dimensionality for the (currently degraded/deterministic)
# EmbeddingGateway — see app/gateway/embedding_gateway.py. Kept in one place
# per ARCHITECTURE_CONTRACTS.md §14 ("tunable defaults... kept in one place").
EMBEDDING_DIM = 256


class User(Base):
    __tablename__ = "users"

    user_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    consent_flags: Mapped[dict] = mapped_column(JSON, default=dict)


# ---------------------------------------------------------------------------
# Phase 3 — Skill Graph + Catalog (design §11.2-§11.3, §15.1, §28)
# ---------------------------------------------------------------------------


class Skill(Base):
    """Node type `Skill` (design §11.2). Curated, read-mostly."""

    __tablename__ = "skills"

    skill_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    label: Mapped[str] = mapped_column(String(256))
    kind: Mapped[str] = mapped_column(String(32))  # concept / tool / practice
    area: Mapped[str] = mapped_column(String(64))
    aliases: Mapped[list] = mapped_column(JSON, default=list)
    description: Mapped[str] = mapped_column(Text, default="")
    assessable: Mapped[bool] = mapped_column(Boolean, default=True)
    # Skill embeddings are not populated this phase (task scope is resource
    # embeddings only); the column exists so the Skill node matches design
    # §11.2's `embedding vector` property without another migration later.
    embedding: Mapped[list | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SkillEdge(Base):
    """Edge types `PREREQUISITE_OF` / `PART_OF` / `RELATED_TO` (design §11.3).

    The other six closed-set edge types (`REQUIRES`, `TARGETS`, `ASSESSES`,
    `MISCONCEPTION_OF`, `ROOTED_IN`, `REMEDIATED_BY`) are cross-node-type
    relationships and live on the tables that already carry both endpoints
    (`RoleRequirement`, `ResourceSkill`, `PracticeItem.skill_id`,
    `Misconception.skill_id`/`root_skill_id`/`remediation_candidates`) rather
    than duplicated here — see app/graph/loader.py, which materializes all
    nine edge types as NetworkX edges regardless of which table they live in.
    """

    __tablename__ = "skill_edges"
    __table_args__ = (UniqueConstraint("from_skill", "to_skill", "type", name="uq_skill_edge"),)

    edge_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    from_skill: Mapped[str] = mapped_column(String(128), ForeignKey("skills.skill_id"), index=True)
    to_skill: Mapped[str] = mapped_column(String(128), ForeignKey("skills.skill_id"), index=True)
    type: Mapped[str] = mapped_column(String(32))  # PREREQUISITE_OF / PART_OF / RELATED_TO
    strength: Mapped[str | None] = mapped_column(String(8), nullable=True)  # hard / soft (PREREQUISITE_OF only)
    min_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    weight: Mapped[float | None] = mapped_column(Float, nullable=True)  # RELATED_TO only
    source: Mapped[str] = mapped_column(String(32))  # curated / llm_draft_reviewed / imported_candidate
    reviewed_by: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Role(Base):
    """Node type `Role` (design §11.2)."""

    __tablename__ = "roles"

    role_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    title: Mapped[str] = mapped_column(String(256))
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RoleRequirement(Base):
    """Edge type `REQUIRES` (Role → Skill, design §11.3)."""

    __tablename__ = "role_requirements"
    __table_args__ = (UniqueConstraint("role_id", "skill_id", name="uq_role_requirement"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    role_id: Mapped[str] = mapped_column(String(128), ForeignKey("roles.role_id"), index=True)
    skill_id: Mapped[str] = mapped_column(String(128), ForeignKey("skills.skill_id"), index=True)
    required_level: Mapped[int] = mapped_column(Integer)  # 1-3
    weight: Mapped[int] = mapped_column(Integer)  # core 3 / important 2 / nice 1


class Misconception(Base):
    """Node type `Misconception` (design §11.2). Field names follow design
    §28's conceptual schema (`skill_id`, `root_skill_id`, `signature`) rather
    than the domain-pack JSON's (`affected_skill`, `root_prerequisite`,
    `manifestation`); the ingestion loader (app/catalog/ingest.py) does that
    rename. `remediation_candidates` is an addition beyond §28's field list —
    it is what makes the `REMEDIATED_BY` edge type (Misconception → Resource,
    design §11.3) materializable; see Contract Changes.
    """

    __tablename__ = "misconceptions"

    misconception_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    description: Mapped[str] = mapped_column(Text, default="")
    skill_id: Mapped[str] = mapped_column(String(128), ForeignKey("skills.skill_id"), index=True)  # MISCONCEPTION_OF
    root_skill_id: Mapped[str] = mapped_column(String(128), ForeignKey("skills.skill_id"), index=True)  # ROOTED_IN
    signature: Mapped[str] = mapped_column(Text, default="")
    severity: Mapped[str] = mapped_column(String(16))
    remediation_candidates: Mapped[list] = mapped_column(JSON, default=list)  # REMEDIATED_BY -> Resource ids
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Resource(Base):
    """Node type `Resource` (design §11.2, §15.1)."""

    __tablename__ = "resources"

    resource_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    title: Mapped[str] = mapped_column(String(256))
    url: Mapped[str] = mapped_column(String(1024))
    provider: Mapped[str] = mapped_column(String(128))
    type: Mapped[str] = mapped_column(String(32))  # video / article / docs / course / exercise / project / book_chapter
    difficulty: Mapped[int] = mapped_column(Integer)  # 1-3
    duration_min: Mapped[int] = mapped_column(Integer)
    modality: Mapped[str] = mapped_column(String(16))  # watch / read / do
    prerequisite_skill_ids: Mapped[list] = mapped_column(JSON, default=list)
    learning_objective_text: Mapped[str] = mapped_column(Text, default="")
    audience: Mapped[str] = mapped_column(String(32))
    language: Mapped[str] = mapped_column(String(16))
    cost: Mapped[str] = mapped_column(String(16))
    curation_tier: Mapped[str] = mapped_column(String(16))  # curated / community / unvetted
    reviewed_by: Mapped[str] = mapped_column(String(128))
    last_verified_at: Mapped[date | None] = mapped_column(nullable=True)
    link_status: Mapped[str] = mapped_column(String(16))  # ok / redirected / broken
    embedding: Mapped[list | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ResourceSkill(Base):
    """Edge type `TARGETS` (Resource → Skill, design §11.3)."""

    __tablename__ = "resource_skills"
    __table_args__ = (UniqueConstraint("resource_id", "skill_id", name="uq_resource_skill"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    resource_id: Mapped[str] = mapped_column(String(128), ForeignKey("resources.resource_id"), index=True)
    skill_id: Mapped[str] = mapped_column(String(128), ForeignKey("skills.skill_id"), index=True)
    level_from: Mapped[int] = mapped_column(Integer)
    level_to: Mapped[int] = mapped_column(Integer)


class PracticeItem(Base):
    """Node type `PracticeItem` (design §11.2). `purpose`, `explanation`,
    `generated_by`, `validated_by`, `graph_version` are additions beyond
    design §28's field list, carried over verbatim from the domain-pack JSON
    to preserve source/review metadata (see Contract Changes).
    """

    __tablename__ = "practice_items"

    item_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    skill_id: Mapped[str] = mapped_column(String(128), ForeignKey("skills.skill_id"), index=True)  # ASSESSES
    type: Mapped[str] = mapped_column(String(16), default="mcq")
    difficulty: Mapped[str] = mapped_column(String(16))  # easy / medium / hard
    purpose: Mapped[str] = mapped_column(String(32), default="practice")  # practice / probe / resolution-check / ...
    stem: Mapped[str] = mapped_column(Text)
    options: Mapped[list] = mapped_column(JSON, default=list)  # [{text, is_key, misconception_id}]
    explanation: Mapped[str] = mapped_column(Text, default="")
    validated: Mapped[bool] = mapped_column(Boolean, default=False)
    generated_by: Mapped[str] = mapped_column(String(64), default="")
    validated_by: Mapped[str] = mapped_column(String(128), default="")
    graph_version: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LearnerProfile(Base):
    """design §28. One row per `User` (enforced by `unique=True` on
    `user_id` — this project treats "user" and "learner" as 1:1 for now;
    design doesn't specify otherwise). `target_role_id` must resolve against
    the curated `Role` table (Phase 3) — an unsupported role is rejected at
    the API layer, never silently accepted (ARCHITECTURE_CONTRACTS.md §5)."""

    __tablename__ = "learner_profiles"

    learner_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.user_id"), unique=True, index=True)
    target_role_id: Mapped[str] = mapped_column(String(128), ForeignKey("roles.role_id"))
    career_goal: Mapped[str] = mapped_column(Text, default="")
    experience_summary: Mapped[str] = mapped_column(Text, default="")
    weekly_hours: Mapped[float] = mapped_column(Float)
    preferences: Mapped[dict] = mapped_column(JSON, default=dict)  # modality order, language, session length
    constraints: Mapped[dict] = mapped_column(JSON, default=dict)  # e.g. fixed days off
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Document(Base):
    """design §28. `storage_ref` is a local filesystem path (design §35:
    "local volume or S3-compatible bucket" — this phase implements the local
    volume) or, for a GitHub-sourced pseudo-document, the repo URL itself.
    """

    __tablename__ = "documents"

    document_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    learner_id: Mapped[str] = mapped_column(String(36), ForeignKey("learner_profiles.learner_id"), index=True)
    type: Mapped[str] = mapped_column(String(16))  # pdf / docx / text / github
    storage_ref: Mapped[str] = mapped_column(String(1024))
    text_hash: Mapped[str] = mapped_column(String(64), default="")  # sha256 of the scrubbed extracted text
    parse_status: Mapped[str] = mapped_column(String(32))  # parsed / empty / needs_text_paste / error
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Evidence(Base):
    """design §28. Written only by the confirm-claims commit path
    (`app/profiling/commit.py`), never directly by the Profiler agent
    (ARCHITECTURE_CONTRACTS.md §2: "Profiler ... No — emits ExtractedClaims
    only")."""

    __tablename__ = "evidence"

    evidence_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    learner_id: Mapped[str] = mapped_column(String(36), ForeignKey("learner_profiles.learner_id"), index=True)
    skill_id: Mapped[str] = mapped_column(String(128), ForeignKey("skills.skill_id"), index=True)
    tier: Mapped[str] = mapped_column(String(4))  # E0 / E1 / E2 / E3
    source_type: Mapped[str] = mapped_column(String(32))  # intake / document / github / assessment
    document_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("documents.document_id"), nullable=True)
    span_text: Mapped[str] = mapped_column(Text, default="")
    span_offsets: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # {"start": int, "end": int}
    assessment_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    extracted_by_run: Mapped[str | None] = mapped_column(String(36), nullable=True)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LearnerSkillState(Base):
    """design §28. `alpha`/`beta` seed from the tier's default prior
    (ARCHITECTURE_CONTRACTS.md §3) when evidence is confirmed; real
    assessment-driven Bayesian updates (correct/incorrect deltas) are the
    Mastery Updater's job (Phase 7, Assessment — not implemented here). With
    `n_obs = 0` (no assessed items yet), `band` is always `unknown` regardless
    of tier or prior — design §10.4's band table only names bands other than
    Unknown in terms of a *mastery estimate* that assessed observations make
    meaningful; a prior alone isn't evidence of a mastery level, just of
    *some* evidence existing. See Contract Changes for this simplification.
    """

    __tablename__ = "learner_skill_states"
    __table_args__ = (UniqueConstraint("learner_id", "skill_id", name="uq_learner_skill_state"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    learner_id: Mapped[str] = mapped_column(String(36), ForeignKey("learner_profiles.learner_id"), index=True)
    skill_id: Mapped[str] = mapped_column(String(128), ForeignKey("skills.skill_id"), index=True)
    alpha: Mapped[float] = mapped_column(Float)
    beta: Mapped[float] = mapped_column(Float)
    band: Mapped[str] = mapped_column(String(16))  # unknown / learning / developing / proficient
    confidence: Mapped[str] = mapped_column(String(8))  # low / medium / high
    n_obs: Mapped[int] = mapped_column(Integer, default=0)
    tier_max: Mapped[str] = mapped_column(String(4))  # E0-E3
    last_assessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PendingClaim(Base):
    """Addition beyond design §28's table list — the staging area for
    `ExtractedClaim`s between a G1 run (`parse_documents` -> `extract_claims`
    -> `verify_evidence` -> `normalize_skills`) and the human confirmation
    step (`POST /api/learners/me/claims/confirm`). Design's `RunState`
    (§9.2) would normally hold this as in-flight, checkpointed graph state,
    but Phase 1 did not build a Postgres-backed LangGraph checkpointer (it's
    still in-memory only — see IMPLEMENTATION_STATE.md "Known Issues"), so
    this table is the durable hand-off between the two HTTP requests
    instead. See Contract Changes.

    Claims that fail span verification (`dropped_unverified`) or that trip
    the prompt-injection detector (`dropped_injection`) are never written
    here at all — they are counted in the run's trace/summary only, per
    design §22.5's "no span means no evidence" and §22.6's "flagged content
    excluded from evidence."
    """

    __tablename__ = "pending_claims"

    claim_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    learner_id: Mapped[str] = mapped_column(String(36), ForeignKey("learner_profiles.learner_id"), index=True)
    run_id: Mapped[str] = mapped_column(String(36), index=True)
    document_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("documents.document_id"), nullable=True)
    skill_label: Mapped[str] = mapped_column(String(256))
    category: Mapped[str] = mapped_column(String(64), default="")
    context_type: Mapped[str] = mapped_column(String(32))  # skills_list/project/experience/education/certificate
    claimed_level_cue: Mapped[str | None] = mapped_column(String(128), nullable=True)
    verbatim_span: Mapped[str] = mapped_column(Text)
    span_offsets: Mapped[dict] = mapped_column(JSON)  # {"start": int, "end": int}
    tier: Mapped[str] = mapped_column(String(4))  # E0-E2, assigned by the Evidence Verifier (design §22.4)
    normalized_skill_id: Mapped[str | None] = mapped_column(String(128), ForeignKey("skills.skill_id"), nullable=True)
    normalization_method: Mapped[str] = mapped_column(String(24))  # exact_alias/embedding/llm_disambiguation/unmapped
    normalization_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending / confirmed / removed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GraphMeta(Base):
    """Graph-versioning history (ARCHITECTURE_CONTRACTS.md §5: "Graph is
    curated offline, versioned... graph_version"). One row per successful
    catalog ingestion run — an append-only audit trail, not a singleton, so
    "which graph_version was active when" is answerable later.
    """

    __tablename__ = "graph_meta"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    graph_version: Mapped[str] = mapped_column(String(64), index=True)
    loaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    source: Mapped[str] = mapped_column(String(512))  # e.g. path to data/dataset/
    skill_count: Mapped[int] = mapped_column(Integer)
    role_count: Mapped[int] = mapped_column(Integer)
    edge_count: Mapped[int] = mapped_column(Integer)
    resource_count: Mapped[int] = mapped_column(Integer)
    misconception_count: Mapped[int] = mapped_column(Integer)
    item_count: Mapped[int] = mapped_column(Integer)


# ---------------------------------------------------------------------------
# Phase 5 — Planner (design §16, §25.2, §28; ARCHITECTURE_CONTRACTS.md §10/§16)
# ---------------------------------------------------------------------------


class WeeklyPlan(Base):
    """design §28. One row per (learner, week); `current_revision_id` points
    at the `PlanRevision` whose `PlanItem`s are the ones actually in effect
    -- `PlanItem.revision_id` scopes every item to the revision it belongs
    to, so superseded revisions' items are never mistaken for current ones
    (design §16.1's rolling-horizon model: future weeks are *regenerated*,
    not edited in place)."""

    __tablename__ = "weekly_plans"

    plan_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    learner_id: Mapped[str] = mapped_column(String(36), ForeignKey("learner_profiles.learner_id"), index=True)
    week_index: Mapped[int] = mapped_column(Integer)
    hours_budget: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft / committed
    current_revision_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PlanRevision(Base):
    """design §28. `cause_type` is `initial` (first `create_plan` draft this
    phase produces) or `patch` (`patch_existing_plan`, design §16/§20 -- the
    operator-driven edit Reflection, Phase 8, will later trigger); other
    design §20.5 cause types (`user_override`, `weekly_rollover`, ...) are
    not produced by this phase, only accepted as a value the column can hold
    later without another migration. `operators`/`diff` are `[]`/`{}` for an
    `initial` revision (design §20.5's closed operator set is Reflection's
    vocabulary, Phase 8 -- Phase 5 stores whatever operators/diff a
    `patch_existing_plan` caller supplies, but does not itself decide when
    patching is warranted)."""

    __tablename__ = "plan_revisions"

    revision_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    plan_id: Mapped[str] = mapped_column(String(36), ForeignKey("weekly_plans.plan_id"), index=True)
    revision_no: Mapped[int] = mapped_column(Integer)
    parent_revision_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    cause_type: Mapped[str] = mapped_column(String(24))  # initial / patch / user_override / weekly_rollover / ...
    cause_ref: Mapped[str] = mapped_column(String(256), default="")
    operators: Mapped[list] = mapped_column(JSON, default=list)
    diff: Mapped[dict] = mapped_column(JSON, default=dict)
    degraded: Mapped[bool] = mapped_column(Boolean, default=False)  # fallback planner was used
    overall_reason: Mapped[str] = mapped_column(Text, default="")  # display-only
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reverted_by: Mapped[str | None] = mapped_column(String(36), nullable=True)


class PlanItem(Base):
    """design §28. `practice_item_ids` is an addition beyond §28's single
    `practice_ref?` -- see `app/schemas/common.py`'s `PlanItem` docstring for
    why (no `PracticeSet` generation service exists yet, Phase 7/Assessor)."""

    __tablename__ = "plan_items"

    item_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    plan_id: Mapped[str] = mapped_column(String(36), ForeignKey("weekly_plans.plan_id"), index=True)
    revision_id: Mapped[str] = mapped_column(String(36), ForeignKey("plan_revisions.revision_id"), index=True)
    type: Mapped[str] = mapped_column(String(16))  # resource / practice / project / probe / review
    objective_id: Mapped[str] = mapped_column(String(256))
    skill_id: Mapped[str] = mapped_column(String(128), ForeignKey("skills.skill_id"), index=True)
    resource_id: Mapped[str | None] = mapped_column(String(128), ForeignKey("resources.resource_id"), nullable=True)
    practice_item_ids: Mapped[list] = mapped_column(JSON, default=list)
    est_minutes: Mapped[int] = mapped_column(Integer)
    difficulty: Mapped[int] = mapped_column(Integer)
    day_slot: Mapped[int] = mapped_column(Integer)
    depends_on: Mapped[list] = mapped_column(JSON, default=list)
    reason: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="planned")  # planned / done / skipped


# ---------------------------------------------------------------------------
# Phase 8 -- Assessment, Mastery, Struggle Detection (design §18, §19, §10.4;
# ARCHITECTURE_CONTRACTS.md §2/§17)
# ---------------------------------------------------------------------------


class PracticeSession(Base):
    """Addition beyond design §28's table list -- the server-side staging
    record between `POST /api/learners/me/practice` (assembles a set) and
    `POST /api/practice/{set_id}/submit` (grades it). Holds the item IDs and
    (crucially) the answer keys/misconception tags *server-side only* --
    design §18.3: "Client responses never include the misconception_id or
    the key. Tags are stripped server-side." Same staging-table precedent as
    `PendingClaim` (Phase 2): no Postgres-backed LangGraph checkpointer
    exists to hold this as in-flight run state instead.
    """

    __tablename__ = "practice_sessions"

    set_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    learner_id: Mapped[str] = mapped_column(String(36), ForeignKey("learner_profiles.learner_id"), index=True)
    skill_id: Mapped[str] = mapped_column(String(128), ForeignKey("skills.skill_id"), index=True)
    purpose: Mapped[str] = mapped_column(String(32))  # practice / probe / resolution-check / prereq-block
    item_ids: Mapped[list] = mapped_column(JSON, default=list)
    misconception_id: Mapped[str | None] = mapped_column(String(128), nullable=True)  # set for a resolution-check set
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending / submitted
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Assessment(Base):
    """design §28/§25.2. `items` is the per-item `AssessmentResult.items[]`
    payload (design §25.2: item_id, skill_id, difficulty, chosen_option,
    correct, misconception_id?, time_sec, attempt_no) -- stored as JSON
    rather than a child table since it is written once, atomically, at
    submit time and never queried by individual item (design §18.4: "the
    Mastery Updater consumes the item-level rows" in-process, not via a
    separate table)."""

    __tablename__ = "assessments"

    assessment_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    learner_id: Mapped[str] = mapped_column(String(36), ForeignKey("learner_profiles.learner_id"), index=True)
    purpose: Mapped[str] = mapped_column(String(32))  # practice / probe / resolution-check / prereq-block
    skill_id: Mapped[str] = mapped_column(String(128), ForeignKey("skills.skill_id"), index=True)
    items: Mapped[list] = mapped_column(JSON, default=list)
    score: Mapped[float] = mapped_column(Float)
    prereq_block_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StruggleSignal(Base):
    """design §28/§25.2/§19.2."""

    __tablename__ = "struggle_signals"

    signal_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    learner_id: Mapped[str] = mapped_column(String(36), ForeignKey("learner_profiles.learner_id"), index=True)
    signal_class: Mapped[str] = mapped_column(String(32))  # low_score / repeated_misconception / ...
    skill_id: Mapped[str] = mapped_column(String(128), ForeignKey("skills.skill_id"), index=True)
    confidence: Mapped[str] = mapped_column(String(8))  # low / medium / high
    evidence_ids: Mapped[list] = mapped_column(JSON, default=list)
    counts: Mapped[dict] = mapped_column(JSON, default=dict)
    thresholds_used: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(8), default="open")  # open / closed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LearnerMisconception(Base):
    """design §28's `Learner -HAS_MISCONCEPTION-> Misconception` learner
    overlay. `remediation_cycles` is an addition beyond §28's field list --
    design §20.8's "after two failed remediation cycles -> persistent"
    needs somewhere to count them; not itself an edge/node in the curated
    graph (ARCHITECTURE_CONTRACTS.md §5: only the global `Misconception`
    node is curated, this table is the per-learner status overlay).
    """

    __tablename__ = "learner_misconceptions"
    __table_args__ = (UniqueConstraint("learner_id", "misconception_id", name="uq_learner_misconception"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    learner_id: Mapped[str] = mapped_column(String(36), ForeignKey("learner_profiles.learner_id"), index=True)
    misconception_id: Mapped[str] = mapped_column(String(128), ForeignKey("misconceptions.misconception_id"), index=True)
    status: Mapped[str] = mapped_column(String(16))  # suspected / confirmed / remediating / resolved / persistent
    evidence_ids: Mapped[list] = mapped_column(JSON, default=list)
    remediation_cycles: Mapped[int] = mapped_column(Integer, default=0)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_remediated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# ---------------------------------------------------------------------------
# Phase 9 -- Reflection & Re-planning (design §20, §25.2, §28; this project's
# own numbering -- design calls this "Phase 8")
# ---------------------------------------------------------------------------


class ReflectionRecord(Base):
    """design §28's `ReflectionRecord(reflection_id, learner_id, signal_id,
    result JSONB, validated bool, rounds)`. `result` is the full
    `ReflectionResult` payload (root cause, operators, hypothesis, etc.) that
    was actually applied (or, when `validated=False`, the last attempted one)
    -- the append-only audit trail behind "why did my plan change?" (design
    §21's episodic memory table)."""

    __tablename__ = "reflection_records"

    reflection_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    learner_id: Mapped[str] = mapped_column(String(36), ForeignKey("learner_profiles.learner_id"), index=True)
    signal_id: Mapped[str] = mapped_column(String(36), ForeignKey("struggle_signals.signal_id"), index=True)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    validated: Mapped[bool] = mapped_column(Boolean, default=False)
    rounds: Mapped[int] = mapped_column(Integer, default=0)
    degraded: Mapped[bool] = mapped_column(Boolean, default=False)  # deterministic patch, not the LLM agent, decided this
    plan_revision_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("plan_revisions.revision_id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DecisionRecord(Base):
    """design §28's `DecisionRecord(decision_id, learner_id, type, inputs,
    evidence_ids[], graph_paths, rules_fired, scores, llm_run_id?,
    graph_version, output_ref, created_at)` -- the general-purpose
    "why did the system decide X" audit row design §21 lists as episodic
    memory. This phase writes one per applied reflection/revision; other
    decision types (gap analysis, planning) do not retroactively adopt this
    table -- out of scope, see IMPLEMENTATION_STATE.md.
    """

    __tablename__ = "decision_records"

    decision_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    learner_id: Mapped[str] = mapped_column(String(36), ForeignKey("learner_profiles.learner_id"), index=True)
    type: Mapped[str] = mapped_column(String(32))  # "reflection" this phase; other types reserved for later phases
    inputs: Mapped[dict] = mapped_column(JSON, default=dict)
    evidence_ids: Mapped[list] = mapped_column(JSON, default=list)
    graph_paths: Mapped[list] = mapped_column(JSON, default=list)  # list[list[skill_id]]
    rules_fired: Mapped[list] = mapped_column(JSON, default=list)
    scores: Mapped[dict] = mapped_column(JSON, default=dict)
    llm_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    graph_version: Mapped[str] = mapped_column(String(64), default="")
    output_ref: Mapped[str] = mapped_column(String(36), default="")  # the resulting PlanRevision.revision_id
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ---------------------------------------------------------------------------
# Phase 12 -- Observability + record/replay (design §31, §33.5, §38.3)
# ---------------------------------------------------------------------------


class AgentRun(Base):
    """design §28's `AgentRun`: one row per traced API request ("run").

    `run_id` is the `X-Run-Id` the client asked to trace, or a server-generated
    UUID -- always echoed back in the `X-Run-Id` response header. `user_id` /
    `learner_id` are deliberately *not* foreign keys: a run is an audit record
    that must be writable even for requests that fail before a profile exists.
    Counters are real measurements taken at the LLM Gateway and the planning
    graph; `tokens_*` stay 0 when a provider returns no usage block (never guessed).
    """

    __tablename__ = "agent_runs"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    learner_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    method: Mapped[str] = mapped_column(String(8), default="")
    route: Mapped[str] = mapped_column(String(200), default="")
    graph: Mapped[str] = mapped_column(String(32), default="api")  # onboarding | planning | assessment | tutor | demo | api
    status: Mapped[str] = mapped_column(String(16), default="completed")  # completed | degraded | failed
    http_status: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[float] = mapped_column(Float, default=0.0)
    llm_calls: Mapped[int] = mapped_column(Integer, default=0)
    llm_retries: Mapped[int] = mapped_column(Integer, default=0)
    llm_replays: Mapped[int] = mapped_column(Integer, default=0)
    llm_degraded: Mapped[int] = mapped_column(Integer, default=0)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    planner_loops: Mapped[int] = mapped_column(Integer, default=0)
    retrieval_ms: Mapped[float] = mapped_column(Float, default=0.0)
    degraded: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class AgentStep(Base):
    """design §28's `AgentStep`: one row per trace event inside a run
    (`app.sse.trace.emit` / `span`). `input_ref`/`output_ref` are *references*
    (IDs), never payloads (ARCHITECTURE_CONTRACTS.md §6: agents talk by ID);
    `decision_id` links a step to its `DecisionRecord` when one exists."""

    __tablename__ = "agent_steps"

    step_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id: Mapped[str] = mapped_column(String(64), ForeignKey("agent_runs.run_id"), index=True)
    learner_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    seq: Mapped[int] = mapped_column(Integer, default=0)
    actor: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(24))
    summary: Mapped[str] = mapped_column(Text, default="")
    refs: Mapped[list] = mapped_column(JSON, default=list)
    input_ref: Mapped[str] = mapped_column(String(200), default="")
    output_ref: Mapped[str] = mapped_column(String(200), default="")
    decision_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    duration_ms: Mapped[float] = mapped_column(Float, default=0.0)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(16), default="ok")  # ok | degraded | error
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LlmReplayEntry(Base):
    """The durable record/replay table ARCHITECTURE_CONTRACTS.md §14 requires
    (design §33.5, §38.3): `prompt_hash -> recorded LLMResponse`. Only
    successful, non-degraded live responses are ever recorded."""

    __tablename__ = "llm_replay_entries"

    prompt_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    schema_name: Mapped[str] = mapped_column(String(64), default="")
    tier: Mapped[str] = mapped_column(String(16), default="")
    response: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
