# EduPath — Implementation State

> **Read this file first.** It is the canonical handoff for any Claude Code session
> resuming work on EduPath. It is optimized for fast orientation, not narrative detail —
> for the "why", see `docs/EduPath_System_Design.md` (authoritative) and
> `docs/ARCHITECTURE_CONTRACTS.md` (stable contracts).

---

### Current Phase

**Phase 1 — Foundation. Complete.**
**Phase 3 — Skill Graph + Catalog Engine. Implemented** (Postgres tables,
NetworkX loader, graph validation/versioning, traversal queries, catalog
ingestion, retrieval-preparation infra). Human review pass over the curated
content itself is still outstanding — see "Domain Knowledge Pack" below.
**Phase 2 — Learner Profiling + Evidence Pipeline. Implemented** (intake,
document upload with text-first PDF/DOCX/text extraction + VLM-fallback
hook, Profiler Agent, Evidence Verifier, Skill Normalizer, human
confirmation, basic GitHub metadata).
**Phase 4 — Skill-Gap Engine. Implemented** (deterministic `analyze_gaps`:
statuses, prerequisite closure/ordering, the BLOCKED overlay, priority,
strengths, audit flags, learning objectives with verify-before-teach;
`GET /api/learners/me/gaps`).
**Phase 6 — Resource Retriever/Ranker. Implemented** (graph-anchored
eligibility filter, hybrid dense+keyword retrieval fused by RRF,
deterministic ranking per design §15.3, MMR near-duplicate removal, live
link validation). Planning, assessment and reflection remain out of scope,
per design's phase ordering — Phase 6 landed ahead of Phase 5 (Planner) at
the operator's explicit direction, since a Planner needs real
`ResourceRecommendation[]` to schedule against.

### Overall Project Status

Foundation layer implemented and verified end-to-end: FastAPI backend, Next.js
frontend, PostgreSQL + pgvector via Alembic migrations, a LangGraph
orchestration skeleton, and a Docker Compose stack that builds and runs all
three services together.

The **Skill Graph + Catalog Engine** (Phase 3, design §11/§12/§15) is
implemented: the domain knowledge pack (`data/`, curated offline) loads into
Postgres via a validated ingestion pipeline, and a NetworkX graph built from
those tables answers prerequisite/ancestor/descendant/role-subgraph/
path-explanation queries.

The **Learner Profiling + Evidence Pipeline** (Phase 2, design §10/§22) is
now also implemented: a learner can complete intake (self-reported skills,
target role, career goal, weekly hours, preferences), upload a resume
(PDF/DOCX/text) or point at a GitHub repo, have the system extract
span-verified skill claims (via a real LLM path with a deterministic,
catalog-anchored fallback), normalize them against the curated Skill Graph,
review/edit/remove them, and confirm them into `Evidence` +
`LearnerSkillState` rows. This closes the loop from "raw learner input" to
"graph-anchored, evidence-tiered learner state."

The **Skill-Gap Engine** (Phase 4, design §13) is now also implemented: a
deterministic `analyze_gaps(role, learner_state, graph)` diffs a target
role's subgraph (Phase 3) against a learner's evidence-graded skill state
(Phase 2) to produce per-skill statuses (`MET`/`WEAK`/`UNVERIFIED`/
`MISSING`/`BLOCKED`), priority-ordered root gaps, audit flags (design
§12.4's claim-evidence integrity checks), and `LearningObjective`s —
`UNVERIFIED` gaps become verify-before-teach *probe* objectives, never
beginner lessons. Exposed via `GET /api/learners/me/gaps`. No LLM anywhere
in this decision path.

The **Resource Retriever/Ranker** (Phase 6, design §14.3/§15) is now also
implemented: `ResourceRetrievalService` anchors to a `(skill_id,
target_level)` gap, applies design §14.3's graph-anchored hard eligibility
filter (targeting, difficulty band, prerequisites, link status, duration,
language, modality), runs hybrid dense (embedding cosine) + keyword
(token-overlap) retrieval fused by Reciprocal Rank Fusion, scores every
eligible candidate with design §15.3's weighted formula (level fit,
quality, modality preference, relevance, duration fit, novelty, prior-
failure penalty), and diversifies the top-K via MMR-style same-provider-
and-modality de-duplication. No resource is ever invented — every
`ResourceRecommendation.resource_id` is drawn from the real catalog.
A separate live link-validation job (`backend/scripts/validate_links.py`)
checks every resource URL and records `link_status`/`last_verified_at`.
No planning, assessment, or reflection logic exists yet, by design.

### Completed Phases

| Phase (per design §39.1) | Status |
|---|---|
| 0 — Engineering state protocol | ✅ Done |
| 1 — Foundation (repo skeleton, Docker Compose, FastAPI, Postgres schema, LLM Gateway, Trace Emitter, Next.js shell) | ✅ Done |
| 2 — Learner profiling | ✅ Implemented (intake, document ingestion, Profiler Agent, Evidence Verifier, Skill Normalizer, human confirmation, GitHub metadata path). See "Completed Work" below. |
| 3 — Skill graph + catalog (critical path) | ✅ Implemented (Postgres tables, NetworkX loader, validation, versioning, traversal queries, catalog ingestion, resource embeddings + FTS index). Curated content itself still needs a human review pass (§11.5) before production gap analysis trusts it. |
| 4 — Gap analysis | ✅ Implemented (deterministic Gap Engine: statuses, prerequisite closure/ordering, BLOCKED overlay, priority, strengths, audit flags, learning objectives with verify-before-teach). See "Completed Work" below. |
| 5 — Planner | ❌ Not started |
| 6 — Resource retrieval | ✅ Implemented (hybrid retrieval, deterministic ranking, MMR, link validation job). Landed ahead of Phase 5 at the operator's direction. See "Completed Work" below. |
| 7 — Practice + assessment | ❌ Not started |
| 8 — Reflection / re-planning (core differentiator) | ❌ Not started |
| 9 — Tutor | ❌ Not started |
| 10 — Observability / evaluation / polish | ❌ Not started |

### Current Phase Status

Phase 1 is complete and verified. `docker compose up --build` (from repo
root) builds and starts `postgres`, `api`, and `web`; the API runs its Alembic
migration on container start, the health endpoint reports `database.ok` and
`orchestration.ok` both `true`, and the dashboard page renders that status
live from the browser. Backend test suite (5 tests: health, DB round-trip via
SQLite, LangGraph compile + run) passes. Frontend `npm run build` succeeds.

### Completed Work

- **Backend** (`backend/`): FastAPI app (`app/main.py`) with lifespan startup
  that fails fast if the LangGraph orchestration graph doesn't compile
  (design §30). Pydantic-settings config (`app/config.py`) reading `.env`.
  Structured JSON logging (`structlog`). Global exception handlers mapping
  domain errors (`NotFoundError`, `ValidationFailedError`,
  `UnsupportedRoleError`) and unexpected exceptions to a consistent JSON
  error body (`app/core/errors.py`).
- **API layer** (`app/api/`): versioned router (`app/api/v1/router.py`)
  mounted under `/api`; `GET /api/health` (DB + orchestration check);
  `GET /api/runs/{run_id}/events` (SSE, wired to the in-process `TraceBus`);
  a session/auth boundary dependency (`app/api/deps.py`) that resolves
  `user_id` from a cookie (dev-mode fallback only in `env=dev`) — establishes
  the rule that `learner_id`/`user_id` must never come from the request body
  or an LLM argument (ARCHITECTURE_CONTRACTS.md §7).
- **Database** (`app/db/`): async SQLAlchemy engine/session
  (`postgresql+asyncpg` in Docker/prod, swappable to `sqlite+aiosqlite` for
  tests). One ORM model, `User` (design §28), as the minimal proof of the
  migration framework. Alembic configured (`alembic.ini`,
  `app/db/migrations/`) with one migration (`0001_foundation`) that enables
  the `vector` and `pg_trgm` Postgres extensions and creates `users`. No
  other tables from the design's conceptual schema are created yet — each
  lands with the phase that owns it.
- **LLM Gateway** (`app/gateway/llm_gateway.py`): `ModelTier` enum
  (small/mid/strong), `LLMRequest`/`LLMResponse` schemas, prompt-hash
  keying, a `ReplayCache` interface with an in-memory implementation
  (Postgres-backed record/replay table is added when the first real agent
  call exists, Phase 2), and a `.complete()` method that degrades
  deterministically (`degraded=True`, no exception) when no provider is
  configured — proves the "LLM unavailable → graceful degradation" path
  (design §30) exists from day one.
- **Orchestration** (`app/orchestration/`): `RunState`/`RunCounters` typed
  state (design §9.2 — bounded counters, not free-form memory);
  `build_bootstrap_graph()`, a real compiled two-node LangGraph graph used by
  the health check and tests to prove the framework works; placeholder
  builders for `G1 Onboarding`, `G2 Planning`, `G3 Evidence-Response`,
  `G4 Tutor` that raise `NotImplementedError` naming the owning phase.
- **Agents** (`app/agents/`): shared `Agent` ABC
  (`run(run_id, input_payload) -> dict`) plus one placeholder class per LLM
  agent (`ProfilerAgent`, `PlannerAgent`, `AssessorAgent`, `ReflectionAgent`,
  `TutorAgent`), each raising `NotImplementedError` naming its owning phase.
  No agent has any tool access yet — intentional, since tools with side
  effects must only ever be given to orchestrator commit nodes
  (ARCHITECTURE_CONTRACTS.md §13).
- **Schemas** (`app/schemas/`): `AgentMessage` envelope and `TraceEvent`
  (ARCHITECTURE_CONTRACTS.md §6/§8); placeholder Pydantic models for the
  twelve core schema names listed in ARCHITECTURE_CONTRACTS.md §6
  (`LearnerState`, `SkillState`, `SkillGap`, `LearningObjective`,
  `ResourceRecommendation`, `WeeklyPlan`, `PlanItem`, `AssessmentResult`,
  `StruggleSignal`, `ReflectionResult`, `ReplanRequest`, `ProgressReport`) —
  each currently just `{id fields..., data: dict}`; real fields are added by
  the phase that owns that schema.
- **Services / repositories** (`app/services/`, `app/repositories/`): empty
  `services` package (docstring only, names the ten deterministic services
  design §7 lists) as a stable import location; `UserRepository` as the one
  concrete repository, proving the data-access pattern against `User`.
- **SSE / Trace** (`app/sse/trace.py`): `TraceBus` (per-`run_id` async-queue
  fan-out) and a `trace.step()` async context manager for orchestration nodes
  to emit events. DB persistence of `AgentStep` rows is added once a graph
  actually produces steps worth persisting (Phase 2+).
- **Frontend** (`frontend/`): Next.js 16 (App Router, TypeScript, Tailwind
  v4) scaffolded via `create-next-app`. Base layout with header/nav/footer
  shell (`app/layout.tsx`); landing page (`app/page.tsx`); a dashboard route
  (`app/dashboard/{page,loading,error}.tsx`) that is a real Server Component
  calling the backend's `/api/health` at request time (`export const dynamic
  = "force-dynamic"` — it must never be statically prerendered, since it
  depends on live backend/DB/orchestration state), with a loading skeleton
  and a client-side error boundary using the (Next.js 16) `retry` prop.
  Typed API client (`lib/api-client.ts`) with an `ApiError` class and one
  typed call (`getHealth`) plus a helper for building the SSE run-events URL;
  later phases add typed calls here rather than inventing new fetch
  wrappers.
- **Docker** (`docker-compose.yml` at repo root, `backend/Dockerfile`,
  `frontend/Dockerfile`): three services — `postgres` (`pgvector/pgvector:pg16`
  image, healthcheck-gated), `api` (runs `alembic upgrade head` then
  `uvicorn`, depends on postgres being healthy), `web` (multi-stage Next.js
  build, depends on `api`). Verified: `docker compose up -d --build` builds
  and starts all three; migration runs cleanly; `curl localhost:8000/api/health`
  returns `{"status":"ok",...}`; `curl -o /dev/null -w '%{http_code}'
  localhost:3000/dashboard` returns 200. Torn down with `docker compose down`
  after verification (no volumes left running).
- **Config**: `.env.example` at repo root documenting every environment
  variable Phase 1 introduces (database, feature flags, LLM gateway,
  session secret, frontend origin/API base, log level).
- `.gitignore` added at repo root (`.venv`, `__pycache__`, `.env`,
  `node_modules`, `.next`, OS cruft).

**Phase 3 — Skill Graph + Catalog Engine** (design §11, §12, §15, §28;
ARCHITECTURE_CONTRACTS.md §5/§9):

- **Postgres schema** (`backend/app/db/models.py`, migration
  `0002_skill_graph_catalog`): `Skill`, `SkillEdge`, `Role`,
  `RoleRequirement`, `Misconception`, `Resource`, `ResourceSkill`,
  `PracticeItem`, `GraphMeta` (an addition beyond design §28's conceptual
  list — an append-only graph-version history table; see
  ARCHITECTURE_CONTRACTS.md §9 "Addition (Phase 3)"). List-valued columns use
  the generic `JSON` type (not `ARRAY`/`JSONB`) so the same model works
  against SQLite in tests, per Phase 1's `consent_flags` precedent.
  `Resource.embedding`/`Skill.embedding` use pgvector's `Vector(256)`.
- **Graph validation** (`backend/app/graph/validation.py`): `GraphValidator`
  — a DB-independent port of `data/scripts/validate_dataset.py`'s checks
  (duplicate IDs, missing references, hard-prerequisite DAG cycle detection,
  orphan skills, role/resource coverage, misconception-ancestor consistency,
  single-correct-option items, URL well-formedness) that runs inline during
  ingestion, before anything is written — a bad catalog is rejected, not
  partially loaded.
- **Catalog ingestion** (`backend/app/catalog/ingest.py`,
  `backend/scripts/seed_catalog.py`): `CatalogIngestor` reads
  `data/dataset/*.json`, validates, maps dataset field names to the ORM
  schema (documented per-field in `models.py`'s docstrings — e.g.
  `affected_skill`/`root_prerequisite`/`manifestation` → `skill_id`/
  `root_skill_id`/`signature`, matching design §28's naming), computes
  resource embeddings, and replaces the entire catalog in one transaction
  (`CatalogRepository.replace_all`) — the curated graph is versioned and
  reloaded whole per ingestion run, not diffed row-by-row. Records a
  `GraphMeta` row each run. Verified against both SQLite (test suite) and a
  real Postgres 16 + pgvector container (`docker compose up postgres`,
  `alembic upgrade head`, `python scripts/seed_catalog.py` — all three ran
  clean this session, including a downgrade/upgrade round-trip).
- **Embedding Gateway** (`backend/app/gateway/embedding_gateway.py`): same
  shape as the LLM Gateway — a provider-agnostic interface with a
  deterministic, dependency-free fallback (feature-hashed, L2-normalized bag
  of tokens) used whenever `LLM_PROVIDER=none` (the default), so catalog
  ingestion and resource embeddings work fully offline and reproducibly. A
  real provider/local model is a `NotImplementedError` stub for whichever
  later phase (Resource Retriever, Phase 6) needs semantic-quality
  embeddings.
- **Retrieval preparation** (migration `0002`,
  `backend/app/repositories/catalog_repository.py`): `resources.embedding`
  (pgvector) and a generated `resources.search_vector` `tsvector` column
  (title weight A, `learning_objective_text` weight B) with a GIN index —
  Postgres FTS, design §14.1's keyword-retrieval plane. `CatalogRepository`
  exposes `search_resources_by_text` (FTS) and `search_resources_by_vector`
  (pgvector cosine distance) as retrieval primitives; both are Postgres-only
  and raise `NotImplementedError` under the SQLite test dialect (verified
  live against Postgres this session). **Not implemented**: the full ranking
  formula (design §15.3: level_fit/quality/modality/relevance/duration/
  novelty weights), RRF fusion, and MMR diversification — that is the
  Resource Retriever/Ranker service, explicitly out of this phase's scope.
- **NetworkX graph loader** (`backend/app/graph/loader.py`): `GraphLoader`
  builds one `networkx.MultiDiGraph` holding all five closed-set node types
  (Role, Skill, Misconception, Resource, PracticeItem) and materializes all
  nine closed-set edge types (`PREREQUISITE_OF`, `PART_OF`, `REQUIRES`,
  `TARGETS`, `ASSESSES`, `MISCONCEPTION_OF`, `ROOTED_IN`, `REMEDIATED_BY`,
  `RELATED_TO` — the last stored once in Postgres, materialized both
  directions since it's defined as bidirectional) regardless of which
  relational table an edge's data actually lives in. Node IDs are the
  curated slugs, globally unique across types, so one graph namespace is
  safe. Not yet wired into `app/main.py`'s startup lifespan — no API route
  reads the graph yet, so there is nothing to hold the loaded singleton for;
  that integration lands with Phase 4's first real caller (Gap Engine).
- **Skill Graph Service** (`backend/app/graph/queries.py`):
  `SkillGraphService` — `hard_ancestors`/`hard_descendants`,
  `direct_prerequisites`/`direct_dependents`, `is_dag`, `topological_order`/
  `topological_layers` (optionally over a subset), `role_subgraph` (required
  skills + hard-prerequisite closure, design §12.1's "derived view, not
  stored"; raises `UnknownRoleError` — "role not supported" — for an
  uncurated role per ARCHITECTURE_CONTRACTS.md §5), `explain_skill_path`
  (shortest hard-prerequisite path from a skill to the nearest role-required
  skill — design §14.4's "chain rule → backpropagation → training neural
  networks" example), `shortest_prerequisite_path` (general point-to-point),
  plus `resources_targeting`, `misconceptions_for_skill`,
  `remediation_resources_for_misconception`. Explicitly does **not** compare
  this structure against learner evidence/mastery — that's the Gap Engine
  (Phase 4, not implemented, per this phase's DO NOT IMPLEMENT list).
- **Tests** (`backend/tests/`): 49 new tests across
  `test_graph_validation.py` (11, hand-built fixtures — one violation per
  test), `test_catalog_ingest.py` (9, against the real domain pack —
  counts-match-meta, field-rename correctness, source/review metadata
  preservation, embedding population, reject-invalid-dataset,
  reingestion-replaces-not-duplicates), `test_graph_loader.py` (5, node/edge
  type completeness, bidirectional RELATED_TO, cross-type relationships),
  `test_graph_queries.py` (17, ancestors/descendants/topological
  order/layers/role subgraph/path explanation, all against the real
  158-skill/3-role graph), `test_embedding_gateway.py` (7, determinism,
  normalization, dimensionality). A new `catalog_session` pytest fixture
  (`tests/conftest.py`) ingests the real dataset into an in-memory SQLite DB
  once per test — so these tests double as a regression check on the domain
  pack itself, not just the code. **54 tests total, all passing.**

**Phase 2 — Learner Profiling + Evidence Pipeline** (design §10, §22, §28;
ARCHITECTURE_CONTRACTS.md §2/§13; package `backend/app/profiling/` per §12's
naming convention):

- **Postgres schema** (`backend/app/db/models.py`, migration
  `0003_learner_profiling`): `LearnerProfile`, `Document`, `Evidence`,
  `LearnerSkillState` (design §28), plus `PendingClaim` — an addition beyond
  §28's table list, the staging area for `ExtractedClaim`s between a G1 run
  and the human confirmation step; see "Architectural Decisions" and
  ARCHITECTURE_CONTRACTS.md's Contract Changes for why (no Postgres-backed
  LangGraph checkpointer exists yet to hold this as in-flight `RunState`).
- **Document parsing** (`backend/app/profiling/document_parser.py`):
  type/size/MIME-sniffing validation (design §29 whitelist: PDF, DOCX,
  TXT/MD, PNG/JPG), text-first extraction (PyMuPDF for PDF, python-docx for
  DOCX, direct decode for TXT/MD). Empty/scanned PDFs and raw images are
  flagged `needs_vlm_fallback` rather than treated as an extraction failure.
- **VLM fallback** (`backend/app/gateway/vlm_gateway.py`): same
  provider-agnostic-gateway shape as the LLM/Embedding Gateways. Wired into
  `parse_documents` (a real PDF page is rendered to PNG via PyMuPDF and sent
  through this gateway on an empty/scanned page); degrades deterministically
  to empty text when no vision provider is configured
  (`LLM_PROVIDER=none`, the default) — there is no offline OCR stand-in, so
  this always resolves to design §30's "ask user to paste text" path in this
  environment, exactly as designed, not silently.
- **PII scrubbing** (`backend/app/profiling/pii.py`): regex-based
  email/phone/best-effort-address redaction, run once before chunking so
  every downstream offset is relative to the scrubbed text.
- **Chunking** (`backend/app/profiling/chunker.py`): paragraph-boundary
  chunking with offsets. Built and unit-tested but not wired into the live
  pipeline's critical path — the Profiler processes a resume's full (small)
  scrubbed text in one shot; chunking exists for when a real LLM's context
  window forces a split, not hit at this scale. See "Known Issues".
- **Prompt-injection detection** (`backend/app/profiling/injection.py`):
  pattern-based (design §22.6: "ignore previous instructions", "give me all
  skills", etc.); flagged spans are excluded from evidence entirely (never
  even reach `PendingClaim`), counted in the run summary as
  `dropped_injection`.
- **Profiler Agent** (`backend/app/agents/profiler.py`): real
  `ProfilerAgent.run()`. Tries a real LLM extraction call (mid tier, design
  §33.2) first, retried up to 2× on schema-validation failure
  (ARCHITECTURE_CONTRACTS.md §11); falls back to
  `DeterministicClaimExtractor` (`backend/app/profiling/claim_extraction.py`
  — a catalog-anchored literal substring scan, case-insensitive/word-boundary
  matched) whenever the gateway degrades (no provider — this project's
  default) or both retries fail. Every claim from either path carries a
  verbatim span. `LLM_PROVIDER=none` in tests means the fallback path is
  what the test suite exercises end to end; the LLM path's parsing/retry
  logic is exercised via a scripted stub gateway.
- **Evidence Verifier** (`backend/app/profiling/evidence_verifier.py`):
  deterministic span verification (offset check, then a direct search
  recovery if the claimed offsets are wrong but the span text is real;
  ≥0.9 similarity after whitespace/case normalization, design §22.5) and
  tier assignment (design §22.4's fixed table: `skills_list`→E0,
  `project`/`experience`→E1, `certificate` or a GitHub source→E2). Never
  assigns E3 (assessed-only, Phase 7). Injection flagging happens here too,
  scanning a window around each claim's span.
- **Skill Normalizer** (`backend/app/profiling/skill_normalizer.py`): exact
  alias/label match → embedding top-5 (via `EmbeddingGateway`, cosine
  similarity; skill embeddings computed on the fly and cached per
  normalizer instance, since `Skill.embedding` itself is still unpopulated
  per Phase 3's scope note) → bounded (≤1 call, no retry loop) small-tier
  LLM disambiguation among the top-5 candidates, validated against that
  exact candidate-ID set (ARCHITECTURE_CONTRACTS.md §7: never an invented
  ID) → `unmapped`. A medium-confidence embedding match that the LLM can't
  confirm (degraded, declines, or fails validation) resolves to `unmapped`,
  never a silently-accepted guess.
- **G1 Onboarding graph** (`backend/app/orchestration/graphs.py`'s
  `build_onboarding_graph`): a real 4-node LangGraph
  (`parse_documents → extract_claims → verify_evidence → normalize_skills`,
  design §9.3) terminating at `status="needs_user"`. Does **not** include
  design's next two nodes (`user_confirm`, `gap_analysis`) — `gap_analysis`
  is this phase's explicit "DO NOT IMPLEMENT", and `user_confirm` is a
  separate HTTP request (`POST /api/learners/me/claims/confirm`) rather than
  an in-graph pause, because Phase 1 never built a Postgres-backed LangGraph
  checkpointer to resume a paused run across requests — `PendingClaim` rows
  are the hand-off instead. One document (or one GitHub-derived pseudo
  document) per graph run/API call; multiple files means multiple calls.
  See "Known Issues" and ARCHITECTURE_CONTRACTS.md's Contract Changes.
- **Onboarding orchestration glue** (`backend/app/profiling/onboarding.py`):
  builds the per-run deterministic services from the live catalog, compiles
  and invokes the graph, and persists its output as `PendingClaim` rows
  (skipping only the claims that were dropped before normalization —
  unverified-span or injection-flagged ones never get this far).
- **GitHub tool** (`backend/app/profiling/github_client.py`,
  `github_repo_summary`, design §26.2): languages, README excerpt (first
  1500 chars), top-level file listing, and dependency-manifest filenames via
  the public GitHub REST API — metadata only, no deep code analysis
  (explicitly out of scope this phase). `httpx.AsyncClient` is injected so
  tests use `httpx.MockTransport` (no live network calls). Repo summaries
  feed into the *same* G1 pipeline as a synthetic text document, tagged
  `is_github_source=True` so the Evidence Verifier assigns E2 automatically.
  404/rate-limit/network-error responses degrade to `fetched=False` with a
  reason, never raise into the pipeline.
- **Evidence commit** (`backend/app/profiling/commit.py`):
  `EvidenceCommitService` — the only code path that writes `Evidence`/
  `LearnerSkillState` (design §10.6's read/write matrix). Seeds
  `alpha`/`beta` from the confirmed tier's default prior
  (`backend/app/core/thresholds.py`, ARCHITECTURE_CONTRACTS.md §3); a
  stronger tier upgrades an existing skill state, a weaker one never
  downgrades it. `band` is always `"unknown"` while `n_obs == 0` (no
  assessed items yet — see "Architectural Decisions"). Ignores claim IDs
  that don't belong to the requesting learner or aren't `pending` — never
  trusts client-supplied IDs blindly.
- **API routes** (`backend/app/api/v1/learners.py`, design §27):
  `POST /api/learners` (intake — creates/updates `LearnerProfile`,
  normalizes self-reported skills straight to E0 evidence, rejects an
  unsupported `target_role_id` with "role not supported" per
  ARCHITECTURE_CONTRACTS.md §5), `POST /api/learners/me/documents`
  (multipart file **or** `github_url`, triggers G1, returns a claims
  summary), `GET /api/learners/me/claims/pending`,
  `POST /api/learners/me/claims/confirm`. `learner_id` is always resolved
  from the session (`app/api/deps.py`'s new `get_current_learner_id`),
  never accepted from the request body. Not implemented from design §27's
  table (out of scope, needs Gap Engine/Planner/Assessor): target-role
  change, gaps, plans, practice, chat, dispute, progress, decisions, demo
  seed endpoints.
- **Bug found and fixed via real-Postgres verification**: the session
  boundary's dev-mode fallback (`user_id="dev-user"`, `app/api/deps.py`,
  Phase 1) has no real signup flow behind it, so no `users` row exists for
  it — `LearnerProfile.user_id`'s FK to `users.user_id` failed on real
  Postgres (SQLite, the test dialect, doesn't enforce FKs by default, so
  this was invisible to the automated suite). Fixed with
  `UserRepository.get_or_create` (auto-provisions a minimal `User` row,
  `email_hash` synthesized from `user_id`), called from the intake route
  before creating a `LearnerProfile`. A regression test now covers this
  directly in `test_db_connection.py`, and the fix was re-verified against
  a real Postgres 16 container end-to-end (intake → upload → confirm).
- **Tests** (`backend/tests/`): 106 new tests across
  `test_document_parser.py` (17), `test_pii.py` (5), `test_injection.py`
  (6), `test_evidence_verifier.py` (14), `test_claim_extraction.py` (20),
  `test_skill_normalizer.py` (10, fully controlled stub embedding/LLM
  gateways so which normalization stage handles a claim is deterministic),
  `test_profiler_agent.py` (5, degrade-to-fallback + scripted-gateway
  retry/success paths), `test_github_client.py` (8, `httpx.MockTransport`),
  `test_learners_api.py` (11, full HTTP-layer flow via ASGI transport — a
  new `app_client` fixture in `tests/conftest.py`), `test_commit.py` (9),
  plus 1 regression test in `test_db_connection.py`. **160 tests total, all
  passing** (54 from Phase 1+3, 106 new). Frontend/document-storage temp
  directories are redirected to a session-scoped tmp dir in `conftest.py`
  so tests never write into the repo tree.

**Phase 4 — Skill-Gap Engine** (design §12.3/§12.4/§13; ARCHITECTURE_CONTRACTS.md
§4; package `backend/app/gap/` per §12's naming convention):

- **Core algorithm** (`backend/app/gap/engine.py`): `analyze_gaps(role_id,
  skill_records, evidence_records, graph)` — design §13.3's algorithm
  implemented close to verbatim. A **pure function**: no DB/session, no
  gateway/agent import anywhere in the module (ARCHITECTURE_CONTRACTS.md §4:
  "100% deterministic... no LLM in the decision path"). Takes a
  `SkillGraphService` (Phase 3) plus two small framework-independent record
  types (`LearnerSkillRecord`, `EvidenceRecord`) so the whole algorithm is
  unit-testable with hand-built fixtures, no DB required.
  - **Required level** per scope skill: `max(role-required level, max
    dependent min_level in scope)`, exactly per §13.3.
  - **Tier gate** (`_level_met`, ARCHITECTURE_CONTRACTS.md §3): mastery ≥
    `LEVEL_MASTERY_THRESHOLD[level]` and `tier_max` ≥
    `LEVEL_TIER_REQUIRED[level]`, plus L3's `n_obs ≥ 3` — new constants in
    `backend/app/core/thresholds.py`.
  - **BLOCKED overlay**: a hard prerequisite in `WEAK`/`MISSING` blocks;
    `UNVERIFIED` does not (design §13.2). The overlaid status replaces the
    raw diagnosis on `SkillGapEntry.status`; the raw diagnosis survives on
    `.gap_type` for provenance.
  - **Priority/ordering**: `weight * (1 + log(1 + unmet_dependents))` per
    §13.3, computed for root gaps and blocked skills; `ordering_layer` from
    `SkillGraphService.topological_layers` over the non-`MET` subgraph.
  - **Audit flags** (design §12.4): `claimed_without_evidence` (E0-only,
    role weight ≥ important) and `stale_or_weak_evidence` (E1 claim needed
    at level ≥ 2) are role-scope-restricted; `claim_evidence_mismatch` (a
    PART_OF parent claimed while only some children have evidence — design's
    "Full Stack claimed, evidence only for React" example) deliberately
    scans **all** claimed skills, not just those in the role's scope,
    because a PART_OF parent (e.g. `skill.math_for_ml`) is usually an
    umbrella node with no `PREREQUISITE_OF` edges of its own and therefore
    never appears in any role's derived subgraph — restricting the parent
    search to scope would silently never fire this rule. Children are still
    restricted to scope so the flag only names gaps relevant to the current
    role. A stale/removed `skill_id` in a learner's evidence is skipped
    (`UnknownSkillError` caught), never crashes the report.
  - **Learning objectives** (design §13.5): one per *root gap* (actionable
    now — not blocked). `objective_type="probe"` for `UNVERIFIED` gaps
    (**verify-before-teach**, the phase brief's explicit requirement) vs.
    `"lesson"` for `WEAK`/`MISSING`. `prerequisite_objective_ids` links an
    objective to any direct hard prerequisite that is *also* a root gap
    (e.g. two chained `UNVERIFIED` skills, neither blocking the other).
    `est_minutes_low/high` are deliberately left `None` — design §13.5
    sources them "from candidate resources at this level band," which is
    the Resource Retriever/Ranker's job (Phase 6, not this phase's scope;
    design §14.1 explicitly avoids mixing retrieval planes).
  - `objective_id_for(role_id, skill_id)` is a deterministic
    `obj.<role_id>.<skill_id>` string (no `uuid4`) — see "Architectural
    Decisions" for why gap results aren't persisted.
- **`SkillGraphService` additions** (`backend/app/graph/queries.py`):
  `hard_prerequisite_out_edges` (`(to_skill_id, min_level)` pairs, needed for
  §13.3's required-level formula) and `part_of_children` (needed for the
  `claim_evidence_mismatch` audit).
- **Startup wiring** (`backend/app/main.py`, `backend/app/api/deps.py`): the
  NetworkX graph is now loaded once at process startup and cached on
  `app.state.skill_graph_service` (best-effort, not fail-fast — an
  empty/unseeded catalog is a normal pre-`seed_catalog.py` state).
  `get_skill_graph_service` reads that cache and falls back to a fresh
  per-request load when it's absent — same tradeoff Phase 2's
  `SkillNormalizer` already made, and the only option in the test suite
  today, since the ASGI transport fixture never drives the lifespan.
- **API route** (`backend/app/api/v1/gap.py`, design §27):
  `GET /api/learners/me/gaps` (optional `?role=` override; defaults to the
  learner's `target_role_id`). A bare deterministic-service call — no
  LangGraph run, matching design §27's table (empty "Orchestrator" column
  for this endpoint). Returns `role_id`, `graph_version`, `gaps[]`
  (`SkillGap`, full role-subgraph coverage including `MET` entries),
  `strengths[]`, `audit_flags[]`, `objectives[]` (`LearningObjective`),
  `layers[]` (topological ordering layers, non-`MET` skills only), and
  `prerequisite_edges[]` (hard `PREREQUISITE_OF` edges within scope) — the
  last two specifically for the Phase 5 brief's "expose enough API output
  for the frontend to visualize the gap graph later" requirement.
- **Schemas**: `SkillGap`/`LearningObjective` in `backend/app/schemas/common.py`
  got their real design §25.2 field lists this phase (previously
  `{id fields..., data: dict}` placeholders). `backend/app/schemas/gap.py`
  adds the response-only supporting types (`Strength`, `AuditFlag`,
  `GapGraphEdge`, `GapReport`) — not core §25.2 schema names, same latitude
  Phase 2/3 already used for `RunClaimsSummary`/`GraphMeta`.
- **No persistence added**: gap results are computed fresh on every call, not
  written to new tables — see "Architectural Decisions" for the reasoning
  and how this reads against design §10.6's read/write matrix.
- **Tests**: 41 new — `tests/test_gap_engine.py` (29: every status, the
  BLOCKED overlay and its `UNVERIFIED`-doesn't-block exception, scope
  coverage, strengths, evidence-ID attribution, layering, all three audit
  flags including a real-data replica of the "Full Stack" example via
  `skill.math_for_ml`, learning-objective generation including
  verify-before-teach and the objective-prerequisite chain, unknown-role and
  unknown-skill-id handling — most against the real curated dataset via
  `catalog_session`/`graph_service`, a few against a small hand-built
  `tiny_graph_service` fixture built directly with `GraphLoader.build` where
  the real data's incidental complexity — e.g. `skill.backpropagation`
  actually has three hard prerequisites, not one — would make a
  single-variable assertion fragile), `tests/test_gap_api.py` (8, full
  HTTP-layer flow via the existing `app_client` fixture: role-from-profile
  default, the `?role=` override and its "role not supported" rejection, the
  "no profile yet" 404, response shape, and a real intake→confirm→gaps
  round trip), plus 4 in `tests/test_graph_queries.py` for the two new
  `SkillGraphService` methods (`hard_prerequisite_out_edges`,
  `part_of_children`). **201 tests total, all passing** (160 from Phase
  1-3, 41 new).

**Phase 6 — Resource Retriever/Ranker** (design §14.3, §15;
ARCHITECTURE_CONTRACTS.md §15; package `backend/app/retrieval/`, an
addition beyond design §35's named-package list, same latitude Phase 3 used
for `catalog/`):

- **Pure ranking core** (`backend/app/retrieval/ranker.py`): `recommend()`
  implements design §14.3 points 2-5 end to end as a pure function (no
  DB/gateway import in the module — same "unit-testable with hand-built
  fixtures" shape as `app/gap/engine.py`).
  - **Eligibility filter** (`filter_eligible`/`eligibility_checks`): targets
    the skill (structural, via the caller's candidate fetch), difficulty
    band overlap `[current_level, current_level+1]`, prerequisites MET,
    `link_status == "ok"` (read literally — `"redirected"` does not pass),
    duration vs. session cap, language, modality exclusion. "Prerequisites
    MET or scheduled earlier" only checks MET — no Planner/schedule exists
    yet to know "earlier" (see "Architectural Decisions").
  - **Hybrid retrieval** (`_hybrid_relevance`): dense (cosine similarity
    over the resource's existing `EmbeddingGateway`-computed embedding, the
    same `_cosine` convention `skill_normalizer.py` uses) + keyword
    (token-overlap over title/`learning_objective_text`, title double-
    weighted to approximate Postgres FTS's title-weight-A convention),
    fused by Reciprocal Rank Fusion, normalized to `[0, 1]`. Deliberately
    **not** `CatalogRepository.search_resources_by_text`/
    `search_resources_by_vector` (Postgres-only, untestable under SQLite) —
    see "Architectural Decisions" for the full reasoning.
  - **Ranking** (`score_candidates`): design §15.3's weighted formula
    (`level_fit` 0.35, `quality` 0.20, `modality_pref` 0.15, `relevance`
    0.15, `duration_fit` 0.10, `novelty` 0.05, minus a flat prior-failure
    penalty) — weights live in `backend/app/core/thresholds.py`'s new
    `RESOURCE_RANK_WEIGHTS`/`RESOURCE_PRIOR_FAILURE_PENALTY`/
    `RESOURCE_QUALITY_*`/`RRF_K`/`DEFAULT_SESSION_CAP_MINUTES` constants.
  - **MMR diversification** (`mmr_diversify`): strict first-occurrence-
    per-(provider, modality) selection with graceful duplicate fallback
    only when the eligible pool can't otherwise fill `top_k` — design
    §15.3's literal "removes near-duplicates (same provider and modality)",
    not general embedding-space MMR.
- **Async orchestration** (`backend/app/retrieval/service.py`):
  `ResourceRetrievalService.recommend_for_skill` fetches real
  `Resource`/`ResourceSkill` rows (new `CatalogRepository.get_resources_targeting_skill`),
  computes the query embedding from the skill's label/description via
  `EmbeddingGateway`, and calls the pure core. Raises `UnknownSkillError`
  for an unsupported skill (never silently empty); returns `[]` when the
  skill has no targeting resources or nothing survives the eligibility
  filter.
- **Link validation** (design §15.2): `backend/app/retrieval/link_validator.py`
  (`check_url`/`validate_resources`, `httpx.AsyncClient` injected — same
  pattern as `github_client.py`, HEAD falling back to GET, bounded
  concurrency) is the *live* network check; static URL well-formedness was
  already a build-time invariant in `app/graph/validation.py` (Phase 3).
  New `CatalogRepository.update_link_statuses` bulk-writes results.
  `backend/scripts/validate_links.py` is the "runs before demo and nightly"
  CLI job entrypoint (mirrors `scripts/seed_catalog.py`).
- **Web fallback gateway** (design §14.3 point 6's optional O4 path):
  `backend/app/gateway/web_fallback_gateway.py`, same provider-agnostic
  shape as the LLM/Embedding/VLM Gateways — degrades to `fetched=False`
  (no results) whenever no provider is configured (this project's
  permanent state). `WebFallbackResult` deliberately has no `resource_id`,
  so it can never be mistaken for a real, catalog-backed recommendation.
  Never called automatically by `ResourceRetrievalService` — a caller must
  opt in explicitly, since these results are `unvetted` by construction.
- **Schemas**: `ResourceRecommendation` (`backend/app/schemas/common.py`)
  got its real design §25.2 field list this phase (previously
  `{resource_id, score, data: dict}`); no API route consumes it yet (see
  "No API route this phase" below).
- **No API route added.** Design §27's endpoint table has no row for the
  Resource Retriever/Ranker — it's Planner-internal. Matching that, this
  phase adds no new HTTP surface; `ResourceRetrievalService` is ready for
  the Planner (Phase 5, not yet implemented) to call once it exists.
- **Tests**: 43 new — `tests/test_ranker.py` (25, hand-built
  `ResourceCandidate` fixtures: every eligibility rule individually,
  relevance/RRF normalization, every ranking-formula component including
  modality preference and the prior-failure penalty, MMR duplicate removal
  and its homogeneous-pool fallback, and the full `recommend()` pipeline —
  dedup, "never invents a resource_id", `top_k`), `tests/test_retrieval_service.py`
  (8, against the real curated dataset via `catalog_session`: real
  `get_resources_targeting_skill` results, a full real-data
  `recommend_for_skill` call for `skill.chain_rule` gated on
  `skill.algebra_basics`, empty-on-unmet-prerequisite/too-small-session-cap/
  no-targeting-resources, `UnknownSkillError` on an unsupported skill, and
  `update_link_statuses`), `tests/test_link_validator.py` (8,
  `httpx.MockTransport`: ok/redirected/404/network-error/HEAD-rejected-
  falls-back-to-GET/both-methods-fail), `tests/test_web_fallback_gateway.py`
  (2, degrade-path). **244 tests total, all passing** (201 from Phase 1-4,
  43 new).

### Files Created / Modified

**Backend** (`backend/`):
- `pyproject.toml`, `alembic.ini`, `pytest.ini`, `Dockerfile`, `.dockerignore`
- `app/__init__.py`, `app/main.py` (extended, Phase 4: startup Skill Graph
  cache on `app.state`), `app/config.py`, `app/logging_config.py`
- `app/core/__init__.py`, `app/core/errors.py`
- `app/schemas/__init__.py`, `app/schemas/envelope.py`,
  `app/schemas/common.py` (extended, Phase 4: real `SkillGap`/
  `LearningObjective` field lists; extended, Phase 6: real
  `ResourceRecommendation` field list), `app/schemas/gap.py` (new, Phase 4)
- `app/db/__init__.py`, `app/db/base.py`, `app/db/session.py`,
  `app/db/models.py` (extended, Phase 3 and Phase 2 — see below)
- `app/db/migrations/env.py`, `app/db/migrations/script.py.mako`,
  `app/db/migrations/versions/0001_foundation.py`,
  `app/db/migrations/versions/0002_skill_graph_catalog.py` (Phase 3),
  `app/db/migrations/versions/0003_learner_profiling.py` (new, Phase 2)
- `app/gateway/__init__.py`, `app/gateway/llm_gateway.py`,
  `app/gateway/embedding_gateway.py` (Phase 3),
  `app/gateway/vlm_gateway.py` (new, Phase 2),
  `app/gateway/web_fallback_gateway.py` (new, Phase 6)
- `app/orchestration/__init__.py`, `app/orchestration/state.py`,
  `app/orchestration/graphs.py` (extended, Phase 2: real `build_onboarding_graph`)
- `app/agents/__init__.py`, `app/agents/base.py`,
  `app/agents/profiler.py` (extended, Phase 2: real `ProfilerAgent`),
  `app/agents/planner.py`, `app/agents/assessor.py`,
  `app/agents/reflection.py`, `app/agents/tutor.py`
- `app/services/__init__.py`
- `app/repositories/__init__.py`,
  `app/repositories/user_repository.py` (extended, Phase 2: `get_or_create`),
  `app/repositories/catalog_repository.py` (Phase 3; extended, Phase 6:
  `get_resources_targeting_skill`, `update_link_statuses`),
  `app/repositories/profiling_repository.py` (new, Phase 2)
- `app/graph/__init__.py`, `app/graph/loader.py`,
  `app/graph/queries.py` (extended, Phase 4: `hard_prerequisite_out_edges`,
  `part_of_children`), `app/graph/validation.py` (Phase 3)
- `app/catalog/__init__.py`, `app/catalog/ingest.py` (Phase 3)
- `app/gap/__init__.py`, `app/gap/engine.py` (new package, Phase 4)
- `app/retrieval/__init__.py`, `app/retrieval/ranker.py`,
  `app/retrieval/service.py`, `app/retrieval/link_validator.py` (new
  package, Phase 6)
- `app/profiling/__init__.py`, `app/profiling/document_parser.py`,
  `app/profiling/pii.py`, `app/profiling/chunker.py`,
  `app/profiling/injection.py`, `app/profiling/claim_extraction.py`,
  `app/profiling/evidence_verifier.py`, `app/profiling/skill_normalizer.py`,
  `app/profiling/github_client.py`, `app/profiling/commit.py`,
  `app/profiling/onboarding.py`, `app/profiling/storage.py` (all new
  package, Phase 2)
- `app/core/__init__.py`, `app/core/errors.py`,
  `app/core/thresholds.py` (new, Phase 2 — tunable numeric defaults;
  extended, Phase 4: `LEVEL_MASTERY_THRESHOLD`/`LEVEL_TIER_REQUIRED`/
  `LEVEL_MIN_N_OBS`; extended, Phase 6: `RESOURCE_RANK_WEIGHTS`/
  `RESOURCE_PRIOR_FAILURE_PENALTY`/`RESOURCE_QUALITY_*`/`RRF_K`/
  `DEFAULT_SESSION_CAP_MINUTES`)
- `app/schemas/profiling.py` (new, Phase 2)
- `app/sse/__init__.py`, `app/sse/trace.py`
- `app/api/__init__.py`, `app/api/deps.py` (extended, Phase 2:
  `get_current_learner_id`; extended, Phase 4: `get_skill_graph_service`)
- `app/api/v1/__init__.py`,
  `app/api/v1/router.py` (extended, Phase 4: registers `gap_router`),
  `app/api/v1/health.py`, `app/api/v1/runs.py`,
  `app/api/v1/learners.py` (new, Phase 2), `app/api/v1/gap.py` (new, Phase 4)
- `scripts/seed_catalog.py` (Phase 3 — CLI catalog ingestion entrypoint),
  `scripts/validate_links.py` (new, Phase 6 — CLI link-validation entrypoint)
- `tests/__init__.py`, `tests/conftest.py` (extended: `catalog_session`
  fixture (Phase 3), `app_client` fixture + storage-tmp-dir redirect
  (Phase 2)), `tests/test_health.py`,
  `tests/test_db_connection.py` (extended, Phase 2: `get_or_create`
  regression test), `tests/test_langgraph_init.py`,
  `tests/test_graph_validation.py`, `tests/test_catalog_ingest.py`,
  `tests/test_graph_loader.py`,
  `tests/test_graph_queries.py` (extended, Phase 4: `hard_prerequisite_out_edges`/
  `part_of_children`), `tests/test_embedding_gateway.py` (Phase 3);
  `tests/test_document_parser.py`, `tests/test_pii.py`,
  `tests/test_injection.py`, `tests/test_evidence_verifier.py`,
  `tests/test_claim_extraction.py`, `tests/test_skill_normalizer.py`,
  `tests/test_profiler_agent.py`, `tests/test_github_client.py`,
  `tests/test_learners_api.py`, `tests/test_commit.py` (all new, Phase 2);
  `tests/test_gap_engine.py`, `tests/test_gap_api.py` (all new, Phase 4);
  `tests/test_ranker.py`, `tests/test_retrieval_service.py`,
  `tests/test_link_validator.py`, `tests/test_web_fallback_gateway.py`
  (all new, Phase 6)

**Frontend** (`frontend/`): scaffolded by `create-next-app` (TypeScript,
Tailwind v4, App Router, ESLint), then customized:
- `app/layout.tsx`, `app/page.tsx` (rewritten)
- `app/dashboard/page.tsx`, `app/dashboard/loading.tsx`,
  `app/dashboard/error.tsx` (new)
- `lib/api-client.ts` (new)
- `Dockerfile`, `.dockerignore` (new)
- Untouched from scaffold: `package.json`, `tsconfig.json`, `next.config.ts`,
  `postcss.config.mjs`, `eslint.config.mjs`, `app/globals.css`,
  `public/*.svg`, `AGENTS.md`/`CLAUDE.md` (Next.js-generated version-notice
  pointer — do not delete; `next dev` re-adds it).

**Root**:
- `docker-compose.yml`, `.env.example`, `.gitignore` (new)
- `docs/IMPLEMENTATION_STATE.md` (this file, rewritten)
- `docs/CHANGELOG.md` (entry appended)
- `data/README.md` (new — domain knowledge pack contract/usage)
- `data/scripts/build_dataset.py` (new — canonical source of curated data)
- `data/scripts/validate_dataset.py` (new — validator)
- `data/dataset/{meta,skills,roles,skill_edges,resources,misconceptions,assessment_items}.json` (generated)
- `data/dataset/demo/{demo_learner,demo_learner_state,demo_scenario}.json`, `demo_resume.md` (generated)

### Dependencies Installed

**Backend** (`backend/pyproject.toml`): fastapi, uvicorn[standard], pydantic,
pydantic-settings, sqlalchemy, asyncpg, alembic, pgvector, langgraph,
langchain-core, python-multipart, sse-starlette, structlog, httpx,
networkx (Phase 3), **pymupdf, python-docx (Phase 2, new — PDF/DOCX
text-first extraction per design §22.1/§34).**
Dev extra (`[dev]`): pytest, pytest-asyncio, aiosqlite.

**Frontend** (`frontend/package.json`): next 16.3.5, react/react-dom 19.2.8.
Dev: @tailwindcss/postcss, tailwindcss v4, typescript, eslint,
eslint-config-next, @types/*.

### Environment Variables Required

See `.env.example` at repo root (copy to `.env`). Summary:
`ENV`, `DATABASE_URL` (+ `POSTGRES_USER`/`PASSWORD`/`DB` for Compose),
`REPLAY_MODE`, `DEMO_MODE`, `LLM_PROVIDER` (`none` disables real calls),
`LLM_API_KEY`, `LLM_SMALL_MODEL`/`MID_MODEL`/`STRONG_MODEL`,
`SESSION_SECRET`, `FRONTEND_ORIGIN`, `NEXT_PUBLIC_API_BASE_URL`,
`LOG_LEVEL`. No real provider key is required yet — `LLM_PROVIDER=none` is
the default and the gateway degrades deterministically. **New this phase:**
`GITHUB_TOKEN` (optional; unauthenticated GitHub API requests work but are
more tightly rate-limited), `DOCUMENT_STORAGE_DIR` (default
`./storage/documents`, relative to the backend process's cwd; gitignored).

### Database Status

Postgres 16 + pgvector, running via Docker Compose, migrated with Alembic.
Three migrations: `0001_foundation` (`vector`/`pg_trgm` extensions, `users`),
`0002_skill_graph_catalog` (`skills`, `skill_edges`, `roles`,
`role_requirements`, `misconceptions`, `resources`, `resource_skills`,
`practice_items`, `graph_meta`, plus a generated `resources.search_vector`
tsvector column with a GIN index), and `0003_learner_profiling`
(`learner_profiles`, `documents`, `evidence`, `learner_skill_states`,
`pending_claims`). All three verified this session against a real Postgres
16 + pgvector container: upgrade, downgrade, and re-upgrade all ran clean
for each; `backend/scripts/seed_catalog.py` populated the full 158-skill
domain pack, and a full intake → document-upload → confirm flow was run
against the real container through the actual FastAPI app (not just SQLite)
— this is what caught the `users` FK bug documented above under "Completed
Work".

No other table in the conceptual schema (`LearningObjective`, `Resource`
already exists from Phase 3, `PracticeTask`, `Assessment`,
`LearningActivity`, `StruggleSignal`, `WeeklyPlan`, `PlanItem`,
`PlanRevision`, `ReflectionRecord`, `DecisionRecord`, `AgentRun`,
`AgentStep`, ...) exists yet — each is created by the migration the owning
phase adds. **Phase 4 (Gap Engine) added no migration**: `SkillGap`/
`LearningObjective` results are computed on demand from existing tables
(`learner_skill_states`, `evidence`) plus the in-memory graph, not persisted
— see ARCHITECTURE_CONTRACTS.md §4's "Decided (Phase 4)" note and
"Architectural Decisions" below.

### Domain Knowledge Pack

Created under `data/` (repo root, deliberately decoupled from
`backend/app/` — see `data/README.md` for the full contract). Source of
truth is `data/scripts/build_dataset.py` (Python literals — terser and
easier to review/diff than hand-written JSON); it generates
`data/dataset/*.json`, which `data/scripts/validate_dataset.py` checks.
Regenerate/validate with:

```bash
python data/scripts/build_dataset.py
python data/scripts/validate_dataset.py
```

Current state: **validates with 0 errors and 0 warnings.**
`graph_version = "v0.1.0-domain-pack"`.

| Asset | Count | Notes |
|---|---|---|
| Skills | 158 | 3 roles (design §11.5's example roles): ML Engineer, Data Analyst, Backend Developer. 6 are non-assessable `PART_OF` grouping/umbrella skills. |
| Roles | 3 | `role.ml_engineer` (46 required skills), `role.data_analyst` (30), `role.backend_developer` (50). |
| Skill edges | 203 | `PREREQUISITE_OF` (hard/soft), `PART_OF`, `RELATED_TO` — the closed edge-type set from `ARCHITECTURE_CONTRACTS.md` §5, minus the edge types that live in other files (`REQUIRES` in roles.json, `TARGETS` in resources.json, `ASSESSES`/`MISCONCEPTION_OF`/`ROOTED_IN`/`REMEDIATED_BY` in misconceptions.json/assessment_items.json). Hard-prerequisite subgraph verified acyclic (validator check #3). |
| Resources | 140 | Real URLs only (official docs, Khan Academy, 3Blue1Brown, Kaggle Learn, Hugging Face, OWASP, PostgreSQL/SQLAlchemy docs, etc.) — see `data/README.md` "Link validation" for how these were spot-checked (two stale domains found and fixed: `linuxjourney.com`, `mode.com`). Every role-required skill has ≥ 1 resource. |
| Misconceptions | 18 | Covers the demo chain (chain rule / backprop / training) plus a representative spread of other core skills (SQL joins, hypothesis testing, recursion, Big-O, REST, auth, testing, Docker, relational modeling). |
| Assessment items | 95 | Covers 23 skills, most to the design §11.5 "≥ 6 mixed-difficulty items" standard; **not** exhaustive across all 158 skills — see "Known scope decisions" below. |
| Demo dataset | 4 files | `demo_learner.json`, `demo_resume.md`, `demo_learner_state.json`, `demo_scenario.json` under `data/dataset/demo/` — implements the design §38.1 "Asha" persona and the `Chain Rule → Backpropagation → Training Neural Networks` seeded path, including the `misc.chain_rule_sum` misconception and a scripted-wrong-answer attempt matching §38.2 step 8. |

**Known scope decisions (do not assume beyond these without checking
`data/README.md`):**
- Assessment item bank is an *initial* bank (95 items / 23 skills), not full
  coverage of all 158 skills — `validate_dataset.py`'s coverage report names
  exactly which assessable skills still have 0 items (this report is also now
  available at ingestion/validation time via
  `GraphValidator.validate(...).item_coverage`). Building out full coverage is
  Phase 7 (Assessor) work.
- No entry in this pack has had a **human review pass** yet — every edge,
  resource, misconception and item currently has
  `reviewed_by: "edupath-phase3-curation"` as a placeholder, carried through
  ingestion unchanged. Design §11.5 calls for human review of every drafted
  prerequisite edge before trusting it in production gap analysis; treat this
  as a strong first draft, now loaded into Postgres, but still not
  human-reviewed content.
- `link_status` is seeded `"ok"` for all 140 resources based on a
  spot-check, not a full crawl. Run a real HEAD-request link-validation pass
  before a live demo or before Phase 6 depends on it.
- **This data is now loaded into Postgres and read by application code**
  (`backend/app/catalog/ingest.py`, `backend/app/graph/`) — see the Phase 3
  bullets under "Completed Work" above. `data/dataset/*.json` remains the
  source of truth; re-run `backend/scripts/seed_catalog.py` after any
  regeneration (`python data/scripts/build_dataset.py`) to refresh Postgres.

### API Status

Seven endpoints implemented: `GET /api/health`, `GET /api/runs/{run_id}/events`
(SSE), `POST /api/learners` (intake), `POST /api/learners/me/documents`
(multipart file or `github_url`), `GET /api/learners/me/claims/pending`,
`POST /api/learners/me/claims/confirm`, `GET /api/learners/me/gaps` (Phase
4 — optional `?role=` override). The rest of design §27's table
(target-role change, plans, practice, chat, dispute, progress, decisions,
demo seed) is not implemented yet — each needs the Planner/Assessor/
Reflection later phases explicitly exclude.
`SkillGraphService`/`CatalogRepository` (Phase 3) are still internal
services with no direct HTTP surface of their own beyond `/gaps`; the intake
route reads `CatalogRepository.get_role` for role validation, but nothing
exposes `/skills/{id}` or similar yet. **The Resource Retriever/Ranker
(Phase 6) also has no HTTP surface** — by design (see ARCHITECTURE_CONTRACTS.md
§15: design §27's table has no row for it; it's Planner-internal).
`ResourceRetrievalService` is fully implemented and tested, just not yet
called from any route — the Planner (Phase 5) is its first intended caller.

### Agent Status

The Profiler Agent (A1) is now real (`app/agents/profiler.py`) — see
"Completed Work" above. The other four LLM agents (Planner, Assessor,
Reflection, Tutor) remain placeholder classes raising `NotImplementedError`.
Only one LangGraph business graph exists for real: G1 Onboarding
(`build_onboarding_graph`); G2/G3/G4 remain placeholders naming their owning
phase (5, 8, 9). No agent other than the Profiler has tool access, and the
Profiler's tools (`parse_document`'s underlying parsing, `github_repo_summary`)
have no side effects, per ARCHITECTURE_CONTRACTS.md §13. The Gap Engine
(Phase 4) and the Resource Retriever/Ranker (Phase 6) are **not** LLM
agents — both are deterministic services ARCHITECTURE_CONTRACTS.md §2
explicitly excludes from that list; no LLM call exists anywhere in
`app/gap/` or `app/retrieval/`.

### Tests Status

Backend: **244 tests, all passing** (`backend/tests/`) — run with
`cd backend && python -m pytest -q`. Phase 1's original 5 (health endpoint
shape; DB session + `UserRepository` round-trip; LangGraph bootstrap graph
compiles and runs to `status="completed"`) plus Phase 3's 49 (graph
invariants, catalog ingestion, NetworkX graph loading, prerequisite/role-
subgraph/path-explanation queries, embedding gateway determinism) plus
Phase 2's 106 (document parsing, PII/injection, evidence verification,
claim extraction, skill normalization, the Profiler Agent, the GitHub tool,
the full learners API, evidence commit — see the Phase 2 "Tests" bullet
under "Completed Work" above for the exact breakdown) plus Phase 4's 41
(Gap Engine statuses/BLOCKED overlay/audit flags/learning objectives, the
`/gaps` API route, two new `SkillGraphService` methods — see the Phase 4
"Tests" bullet under "Completed Work" above) plus Phase 6's 43 (ranker
eligibility/hybrid-relevance/scoring/MMR, the retrieval service against
real catalog data, link validation, the web fallback gateway's degrade
path — see the Phase 6 "Tests" bullet under "Completed Work" above). All
run against SQLite (`tests/conftest.py`'s existing dialect-portability
convention); the Postgres-only catalog paths
(`CatalogRepository.search_resources_by_text`/`search_resources_by_vector`,
the generated `search_vector` column) and the full learner-profiling flow
through the real FastAPI app were both verified manually this session
against a real Postgres 16 + pgvector container instead (see "Database
Status" above) rather than added to the automated suite, since the project
has no Postgres-backed CI/test tier yet.

Frontend: no automated test file yet; `npm run build` (verified passing) is
the build test called for in this phase. A real test runner (Vitest/Playwright)
is introduced when there's interactive UI worth testing (Phase 2+).

Docker Compose: verified manually this session (`docker compose up -d
--build`, checked `/api/health` and `/dashboard` respond, then `docker
compose down`). Not yet wired into CI — add a CI workflow when the repo gets
one.

### Known Issues

- `backend/app/core/errors.py` uses `status.HTTP_422_UNPROCESSABLE_ENTITY`,
  which current Starlette flags as deprecated in favor of
  `HTTP_422_UNPROCESSABLE_CONTENT` (cosmetic warning only, not a failure;
  harmless to fix in a later pass).
- The session/auth boundary (`app/api/deps.py`) is a placeholder: a bare
  cookie value with a dev-mode fallback (`session=None` → `"dev-user"` only
  when `env=dev`). There is no real login/signup flow. This is intentional
  for Phase 1 (design doc does not specify an auth provider), but note it
  now has a real consequence: `UserRepository.get_or_create` auto-provisions
  a `users` row for whatever `user_id` the boundary hands back, since
  `LearnerProfile` FK-references it (see "Completed Work" above). A real
  auth flow should replace the dev-mode fallback with actually-authenticated
  IDs; `get_or_create` itself is fine to keep (idempotent, self-healing).
- The LLM Gateway's replay cache is in-process only (`InMemoryReplayCache`),
  not yet backed by a Postgres table. ARCHITECTURE_CONTRACTS.md §14 requires
  a durable record/replay cache — the Profiler Agent (Phase 2) is now the
  first real agent call, so this is worth prioritizing before Phase 4+ adds
  more agent calls on top of the same gap.
- No CI pipeline exists to run backend tests / frontend build / compose
  startup automatically on push.
- Docker Desktop must be running before `docker compose up`; if its engine
  is stopped, compose fails at the daemon connection (not a config issue —
  `docker compose config` validates independent of the daemon).
- **(Resolved, Phase 4)** The Skill Graph is now loaded at app startup
  (`app/main.py`'s `lifespan`, cached on `app.state.skill_graph_service`) —
  see "Completed Work" above. Phase 2's `onboarding.py` still builds a fresh
  `SkillNormalizer`/`DeterministicClaimExtractor` from the catalog on every
  document-upload request rather than reusing the startup-loaded graph
  (acceptable at 158 skills / SQLite-in-memory-pool speed, real per-request
  cost at Postgres scale) — that migration to the shared cache is still
  open, now that the cache itself exists.
- `CatalogRepository.search_resources_by_text`/`search_resources_by_vector`
  raise `NotImplementedError` under SQLite (Postgres-only SQL/operators) —
  by design, but it means the automated test suite cannot exercise them; they
  were only verified manually against a live Postgres container this
  session, not via `pytest`. Re-verify manually after touching either method
  until the project has a Postgres-backed CI tier.
- **(Phase 2)** `chunk_text` (`app/profiling/chunker.py`) is implemented and
  unit-tested but not wired into the live `parse_documents` node — the
  Profiler currently processes a document's full scrubbed text in one call.
  Fine at resume scale; revisit if a real provider's context window ever
  forces a split (claim offsets would then need remapping from
  chunk-relative back to document-relative, which nothing currently does).
- **(Phase 2)** `POST /api/learners/me/documents` accepts exactly one file
  (or one `github_url`) per call, not true multi-file batches, even though
  design §27's table shows `file(s)`. Uploading several documents means
  several calls (several G1 runs, several `run_id`s) — see Contract Changes.
- **(Phase 2)** The VLM fallback (`app/gateway/vlm_gateway.py`) always
  degrades to empty text in this environment (no vision provider
  configured) — there is no offline OCR stand-in, unlike text extraction and
  embeddings which have deterministic fallbacks. A scanned PDF or a
  certificate image will currently always end up `needs_text_paste`
  (design §30's documented behavior, not a bug), until a real provider is
  wired in.
- **(Phase 2)** `PendingClaim` rows are never cleaned up or expired — a
  learner who never confirms/removes an extracted claim leaves it `pending`
  indefinitely. No garbage-collection job exists yet; not a correctness bug
  (claims are learner-scoped and harmless at rest) but worth a TTL/cleanup
  pass before a long-lived deployment.
- **(Phase 4)** With this project's evidence-tier priors (E0-E2 Beta counts,
  ARCHITECTURE_CONTRACTS.md §3), the mastery *estimate* (`alpha/(alpha+beta)`)
  caps at 0.4 for E1/E2 — below every level's mastery threshold (L1 ≥ 0.50).
  So pre-assessment evidence (everything this project can produce today,
  since the Mastery Updater is Phase 7) lands `WEAK` at best, never `MET`,
  even a strong E2 artifact like a verified GitHub repo. This is a faithful
  implementation of the tier-gate contract as numerically specified, not a
  Gap Engine bug — see ARCHITECTURE_CONTRACTS.md §3's note and
  "Architectural Decisions" below for the full reasoning. It does mean
  design §13.4's worked example (Python `MET` from GitHub evidence alone)
  won't reproduce exactly until Phase 7 lands or the priors are retuned.
- **(Phase 4, still open post-Phase 6)** `LearningObjective.est_minutes_low/high`
  are still always `None` — the Gap Engine (`app/gap/engine.py`) does not
  call the now-implemented Resource Retriever (`app/retrieval/`) to
  populate them; wiring that is Phase 5's (Planner) job, since that's the
  first place both a `LearningObjective` and its candidate resources need
  to be in scope together. `acceptance_criteria` also still omits design
  §13.5's `no_open_misconceptions_for(skill)` clause — no per-learner
  misconception status table exists yet (design's
  `Learner -HAS_MISCONCEPTION-> Misconception` overlay isn't built; only
  the curated, global `Misconception` node is). Add both once their owning
  phase/table exists.
- **(Phase 4)** `POST /api/learners/me/skills/{skill_id}/dispute` (design
  §12.4: disputing an audit flag) is not implemented — audit flags are
  emitted every call, never suppressed or remembered as disputed. A later
  phase should add the dispute table/endpoint if this matters before a demo.
- **(Phase 6)** No `LearningActivity`/`Assessment` table exists to source
  `learner_history` (novelty / prior-failure-penalty inputs) from live
  data — `ResourceRetrievalService.recommend_for_skill` accepts it as a
  parameter (defaults to empty) rather than querying anything. The
  algorithm is complete and tested; a real caller supplies real history
  once Phase 7/8 writes one of those tables.
- **(Phase 6)** The link-validation job (`scripts/validate_links.py`) has
  not been run this session against the live 140-resource catalog (no
  network access in this environment) — `Resource.link_status` still
  reflects Phase 3's ingestion-time spot-check seed (`"ok"` for all 140),
  not a fresh live check. Run it before trusting `link_status` in a demo.
- **(Phase 6)** Hybrid relevance uses the same deterministic, hashed
  bag-of-tokens embedding fallback as everywhere else in this project
  (`LLM_PROVIDER=none`) — not semantically strong (see
  `app/gateway/embedding_gateway.py`'s existing note from Phase 3). Ranking
  quality should be re-evaluated once a real embedding provider is wired in
  (design §32's labeled query set, still not built).
- **(Phase 6)** `RESOURCE_RANK_WEIGHTS`/`RESOURCE_PRIOR_FAILURE_PENALTY`/
  the quality-recency windows are hand-set defaults per design §15.3,
  unvalidated against real usage data (none exists yet) — calibrate once
  design §32's evaluation set exists, per ARCHITECTURE_CONTRACTS.md §14.

### Architectural Decisions

- **ID format** (ARCHITECTURE_CONTRACTS.md §7 asks implementers to decide and
  record this): `User.user_id` is a UUID v4 string, stored as `String(36)`.
  Follow the same convention (UUID v4 as `String(36)`, or a Postgres native
  `UUID` column) for other learner/run-scoped rows in later phases; curated
  graph/catalog rows (skills, roles) should use stable slugs instead, per the
  same section.
- SQLAlchemy async engine + `asyncpg` driver chosen for Postgres access
  (matches design §34's "async... for ML/agent tooling" rationale); tests use
  `aiosqlite` instead of a live Postgres to keep the suite fast and
  dependency-free — this is a test-only substitution, not a production
  option (pgvector/JSONB-specific features require real Postgres and are
  tested against it once a phase needs them).
- Dashboard page is marked `export const dynamic = "force-dynamic"` because
  it performs a live backend fetch; without this, `next build` tries to
  statically prerender it and fails when the backend isn't reachable at
  build time. Any future page that fetches live backend/DB state should do
  the same.
- **(Phase 3)** The curated catalog is loaded *whole* per ingestion run
  (`CatalogRepository.replace_all`: delete everything, re-insert everything,
  in one transaction), not diffed/upserted row-by-row. This matches the
  design's "graph is curated offline, versioned" model (a new
  `graph_version` means a new full snapshot, not a patch) and avoids
  cross-dialect upsert/conflict-handling complexity. Revisit only if a later
  phase needs incremental catalog updates without a full reload.
- **(Phase 3)** List-valued ORM columns use generic `JSON`, not
  `postgresql.ARRAY`; embeddings use pgvector's `Vector` type, whose distance
  operators are Postgres-only — see ARCHITECTURE_CONTRACTS.md §9 "Decided
  (Phase 3)" for the full rationale (SQLite test-dialect portability).
- **(Phase 3)** `EmbeddingGateway`'s default (`LLM_PROVIDER=none`) fallback is
  a deterministic feature-hashed, L2-normalized bag-of-tokens embedding
  (`EMBEDDING_DIM = 256`, `backend/app/db/models.py`) — not semantically
  strong, but offline, dependency-free, and reproducible (same text -> same
  vector always), matching the LLM Gateway's existing degrade pattern and
  ARCHITECTURE_CONTRACTS.md §14's offline-determinism requirement. Swap in a
  real provider/local model when Phase 6 (Resource Retriever) needs
  semantic-quality ranking — the interface is already provider-agnostic.
- **(Phase 2)** G1 Onboarding stops at `status="needs_user"` and does not
  include design's `user_confirm`/`gap_analysis` nodes; `PendingClaim` rows
  are the hand-off to the separate confirm-claims HTTP request instead of an
  in-graph pause. Reason: no Postgres-backed LangGraph checkpointer exists
  yet to resume a paused run across requests (Phase 1 left this as an open
  item — see the replay-cache bullet above, a related gap). Revisit once
  that checkpointer exists; at that point `user_confirm` could become a real
  interrupt/resume node and `PendingClaim` could potentially be retired in
  favor of checkpointed `RunState`.
- **(Phase 2)** `LearnerSkillState.band` is always `"unknown"` while
  `n_obs == 0`, regardless of tier or the seeded prior's numeric mastery
  estimate. Design §10.4's band table only names Learning/Developing/
  Proficient in terms of a mastery estimate that assessed observations make
  meaningful; a prior alone (E0-E2, no assessment yet) isn't evidence of a
  mastery *level*, just of evidence *existing*. Real banding starts once the
  Mastery Updater (Phase 7) adds assessed observations.
- **(Phase 2)** `EvidenceCommitService._upsert_skill_state` reseeds
  `alpha`/`beta` to the new tier's flat prior on a tier upgrade, rather than
  Bayesian-combining the old and new priors. Simple and matches design's own
  framing (§10.3: "a handful of assessed items can quickly outweigh
  documents" — i.e., tier priors are meant to be overtaken wholesale by
  better evidence, not finely blended). A weaker/equal tier never downgrades
  the state, so this can only move mastery-prior estimates upward over time.
- **(Phase 2)** GitHub repo summaries are modeled as a `Document` row
  (`type="github"`, `storage_ref=repo_url`) and fed through the *same* G1
  pipeline as a synthetic text document (description + languages + manifest
  filenames + README excerpt), rather than a separate code path. This reuses
  claim extraction/verification/normalization as-is and is why a GitHub
  source can get E2 tier automatically (`is_github_source=True` flows
  straight into the existing tier-assignment rule) instead of needing a
  parallel tier-assignment implementation.
- **(Phase 4)** Gap results are computed on demand, not persisted (no new
  migration this phase) — see ARCHITECTURE_CONTRACTS.md §4's "Decided
  (Phase 4)" for the full reasoning against design §10.6's read/write
  matrix. `objective_id_for(role_id, skill_id)` is a deterministic string,
  not a `uuid4`, specifically so `LearningObjective` IDs stay stable and
  referenceable across calls without a table backing them.
- **(Phase 4)** `analyze_gaps` is a pure function over `SkillGraphService`
  plus two small record types (`LearnerSkillRecord`, `EvidenceRecord`), not
  a class or a service that reads the DB itself — the API route
  (`app/api/v1/gap.py`) does the ORM-row-to-record conversion. This mirrors
  `app/graph/queries.py`'s existing shape and is what makes the whole
  algorithm unit-testable with hand-built fixtures and no DB/session at all.
- **(Phase 4)** `claim_evidence_mismatch` (design §12.4) deliberately scans
  every claimed skill graph-wide for a `PART_OF` parent, rather than
  restricting the parent search to the current role's scope like the other
  two audit rules do. A `PART_OF` parent (e.g. `skill.math_for_ml`,
  `skill.backend_fundamentals`) is normally an umbrella node with no
  `PREREQUISITE_OF` edges of its own, so it is typically *not* a
  hard-ancestor of any role-required skill and therefore never appears in
  any role's derived subgraph — scoping the parent search would silently
  make this rule never fire. Children are still scope-restricted so the
  flag only names gaps relevant to the current role.
- **(Phase 4)** `SkillGapEntry.status` is the user-facing status (`BLOCKED`
  overlays the raw diagnosis, per design §13.2); the raw diagnosis survives
  on `.gap_type` (lowercase: `met`/`weak`/`unverified`/`missing`). This
  keeps `BLOCKED`'s "why" inspectable (`blocked_by[]` plus `gap_type`)
  without needing a second lookup.
- **(Phase 6)** Hybrid dense+keyword retrieval is computed in pure Python
  over already-fetched `Resource` rows (cosine similarity against the
  stored `embedding`; token-overlap keyword scoring), not via
  `CatalogRepository.search_resources_by_text`/`search_resources_by_vector`.
  Those two methods are Postgres-only and already documented (Phase 3) as
  "not exercised by pytest" — building the Ranker's core algorithm on top
  of them would make it just as untestable, directly conflicting with this
  phase's explicit test requirements. See ARCHITECTURE_CONTRACTS.md §15 for
  the full reasoning; this is a deliberate deviation from a literal reading
  of design §14.3 point 3 ("run dense and keyword search... fuse by RRF"),
  in favor of dialect-portability and testability — the retrieval *result*
  (RRF-fused, relevance-ranked eligible resources) is the same either way,
  only the SQL-vs-Python mechanism differs.
- **(Phase 6)** `link_status == "ok"` is read literally in the eligibility
  filter — `"redirected"` does not pass. Design §14.3 point 2 states the
  filter as `link_status = ok`, and design §15.1 treats `ok`/`redirected`/
  `broken` as three distinct values, so this is the literal reading, not
  a simplification. Revisit if a later phase's calibration shows
  "redirected but reachable" resources are being filtered out too
  aggressively.
- **(Phase 6)** MMR diversification is a strict first-occurrence-per-
  (provider, modality) selection, not general embedding-space Maximal
  Marginal Relevance — design §15.3's literal closing sentence describes
  "same provider and modality" de-duplication, not corpus-wide diversity
  scoring, so that's what's implemented. Falls back to filling remaining
  slots with duplicates, best score first, only when the eligible pool
  can't otherwise reach `top_k` — a demo/run should still get resources
  rather than an under-filled list over a diversity purity constraint.
- **(Phase 6)** `ResourceRetrievalService`/`recommend()` are not exposed
  via a new API route — design §27's endpoint table has no row for the
  Resource Retriever/Ranker (it's Planner-internal per design §14.3), so
  adding one would be inventing an endpoint the design doc doesn't call
  for. The Planner (Phase 5, not yet implemented) is the intended first
  caller.

### Contract Changes

`docs/ARCHITECTURE_CONTRACTS.md` §2, §5, and §9 updated this phase (see that
file's diff for exact wording); Phase 3's entry above still stands for its
own §5/§9 additions:
- §2: noted the Profiler Agent (A1) is now real, and that it is the only
  currently-implemented LLM agent among the five.
- §9: recorded three more **additions** to design §28's conceptual data
  model, following the same "§28 lists only fields/tables actually used"
  latitude Phase 3 already used for `GraphMeta`: (1) `PendingClaim` — the
  G1-run-to-confirmation staging table, needed because no Postgres-backed
  LangGraph checkpointer exists to hold this as in-flight `RunState`
  instead (see "Architectural Decisions" above); (2) `Document.type`
  includes `"github"` as a pseudo-document type, modeling a GitHub repo
  summary as a synthetic document rather than a separate evidence path;
  (3) `UserRepository.get_or_create` as the documented way `User` rows get
  created under the current placeholder (non-)auth flow, since
  `LearnerProfile.user_id`'s FK now makes a missing `users` row a hard
  failure on Postgres, not just a soft assumption.
- Scope note (not a contract change, but worth flagging near §8 API
  conventions for the next reader): `POST /api/learners/me/documents`
  accepts one file (or one `github_url`) per call, not the batched
  `file(s)` design §27's table shows — see "Known Issues".

`docs/ARCHITECTURE_CONTRACTS.md` §4, §5, §6, and §7 updated Phase 4 (Gap
Engine):
- §4: pointed to `backend/app/gap/engine.py` as the implementation and
  recorded the "computed on demand, not persisted" decision.
- §5: recorded the two new `SkillGraphService` methods and the startup
  lifespan wiring (previously an open item from Phase 3).
- §6: noted `SkillGap`/`LearningObjective` now have real field lists.
- §3 (tier gate): recorded where the level thresholds now live
  (`backend/app/core/thresholds.py`) and the mastery-priors-cap-at-WEAK
  nuance (see "Known Issues").

`docs/ARCHITECTURE_CONTRACTS.md` §2, §6, §9, §12, and §13 updated, and a new
§15 added, this phase (Phase 6, Resource Retriever/Ranker):
- §2: pointed to `backend/app/retrieval/ranker.py`'s `recommend()` as the
  implementation.
- §6: noted `ResourceRecommendation` now has a real field list.
- §9: recorded the two new `CatalogRepository` methods
  (`get_resources_targeting_skill`, `update_link_statuses`).
- §12: recorded `retrieval/` as a package-naming addition (alongside
  Phase 3's `catalog/`).
- §13: recorded the Web Fallback Gateway's implementation and its
  "never confused with a real recommendation" ID-less design.
- New §15 (this file's own numbering, not design's §15): the full set of
  Phase 6 decisions — pure-Python hybrid retrieval instead of the
  Postgres-only FTS/pgvector methods, the literal `link_status == "ok"`
  reading, the MMR-as-de-duplication interpretation, the "prerequisites
  MET only" simplification, "no API route this phase," and the
  `learner_history`-as-parameter decision pending a `LearningActivity`
  table.

### Next Phase

**Phase 5 — Planner** (design §39.1, §16-§19): the Planner Agent (draft/patch
modes) plus the deterministic Plan Validator (V1-V10, ARCHITECTURE_CONTRACTS.md
§10) and Fallback Planner, consuming the Gap Engine's `LearningObjective[]`
(Phase 4, implemented — `GET /api/learners/me/gaps`) and the now-implemented
Resource Retriever/Ranker's `ResourceRecommendation[]` (Phase 6,
`ResourceRetrievalService.recommend_for_skill`) to produce a
`WeeklyPlan`/`PlanItem[]`. This is also the natural place to: wire
`LearningObjective.est_minutes_low/high` from real candidate resources
(both a `LearningObjective` and its candidates are finally in scope
together at the Planner); add `POST /api/learners/me/plans` (design §27,
the first real caller of `app/retrieval/`); and populate
`ResourceUsageRecord`/`learner_history` from whatever activity-tracking
table the Planner's "Act" loop introduces.

Still open on **Phase 3**: a human review pass over the curated content
(§11.5) — every edge/resource/misconception/item still shows
`reviewed_by: "edupath-phase3-curation"`, a placeholder. The live
link-validation sweep itself is now implemented
(`scripts/validate_links.py`, Phase 6) but has not been *run* this session
(no network access in this environment) — run it before trusting
`link_status` in a demo.

Still open on **Phase 2**: a Postgres-backed LLM Gateway replay cache (now
overdue — the Profiler is a real agent call); wiring Phase 2's per-request
`SkillNormalizer`/`DeterministicClaimExtractor` construction onto the
startup-loaded graph cache Phase 4 introduced; true multi-file document
upload (currently one file per call).

Still open on **Phase 4**: the `no_open_misconceptions_for(skill)`
acceptance-criteria clause (needs a per-learner misconception status table,
not built yet); the skill-dispute endpoint (design §12.4,
`POST /api/learners/me/skills/{skill_id}/dispute`);
`LearningObjective.est_minutes_low/high` (Resource Retriever now exists,
Phase 6 — wiring the two together is Phase 5's job, per "Next Phase" above).

Still open on **Phase 6**: no `LearningActivity`/`Assessment` table exists
yet to source real `learner_history` (novelty/prior-failure-penalty
inputs) from — Phase 7/8's job; ranking weights are unvalidated hand-set
defaults (design §32's evaluation set doesn't exist yet); the live
web-search provider behind `WebFallbackGateway` is unimplemented (optional
per the phase brief).

### Exact Next Task

1. Implement the Planner Agent (`app/agents/planner.py`, currently a
   placeholder) in draft/patch modes per design §16-§17, calling
   `GET /api/learners/me/gaps` (Phase 4) for objectives and
   `ResourceRetrievalService.recommend_for_skill` (Phase 6) for candidate
   resources per objective.
2. Implement the deterministic Plan Validator (`app/planning/` per the
   package-naming convention) enforcing V1-V10 and the always-succeeds
   Fallback Planner (ARCHITECTURE_CONTRACTS.md §10).
3. Add `POST /api/learners/me/plans` / `GET /api/learners/me/plans/current`
   (design §27) — the first real callers of both `app/gap/` and
   `app/retrieval/` from a single orchestrated flow (likely G2 Planning,
   design §9.3).
4. Test against real Gap Engine + Resource Retriever output from Phase 2's
   intake + document flow, not just the seeded demo state.
5. Before trusting the graph in a live demo: run the human review pass
   (Phase 3) and the now-implemented live link-validation sweep
   (`scripts/validate_links.py`, Phase 6) noted above.
6. Add the Postgres-backed LLM Gateway replay cache (Phase 1's open item,
   now overdue since the Profiler is a real agent call) before adding more
   agents (Planner) on top of the same gap.

### Commands To Verify Current State

```bash
# Domain knowledge pack (from repo root; stdlib-only, any Python 3.9+)
python data/scripts/build_dataset.py
python data/scripts/validate_dataset.py

# Backend tests (from backend/, with .venv activated or via pip install -e ".[dev]")
cd backend && python -m pytest -q

# Frontend build
cd frontend && npm run build

# Skill graph + catalog + learner-profiling migrations and seed (from backend/;
# requires a running, reachable Postgres — e.g. `docker compose up -d postgres`
# from repo root)
cd backend && alembic upgrade head
python scripts/seed_catalog.py

# Live link-validation sweep (Phase 6; requires network access and a seeded DB)
python scripts/validate_links.py

# Full stack (from repo root; requires Docker Desktop running)
docker compose up -d --build
curl http://localhost:8000/api/health
curl -o /dev/null -w "%{http_code}\n" http://localhost:3000/dashboard
docker compose down
```
