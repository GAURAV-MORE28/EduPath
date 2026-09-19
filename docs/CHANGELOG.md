# EduPath — Changelog

All notable changes to the EduPath project are recorded here, newest first.
This is an engineering changelog (what changed and why it matters for
implementation state), not a marketing changelog.

Format per entry: `## [Phase N | date] Short title` followed by a short bullet list.

---

## [Phase 6 | 2026-09-19] Hybrid Resource Retrieval + Ranking

- Added `backend/app/retrieval/` (design §14.3/§15; ARCHITECTURE_CONTRACTS.md
  §2, an addition beyond design §35's named-package list, same latitude
  Phase 3 used for `catalog/`):
  - `ranker.py`: `recommend()` — a **pure function** (no DB/gateway import)
    implementing design §14.3 points 2-5: eligibility filter (targets the
    skill, difficulty band overlap, prerequisites MET, `link_status == "ok"`
    read literally, duration vs. session cap, language, modality exclusion),
    hybrid dense (embedding cosine, reusing `EmbeddingGateway`) + keyword
    (token-overlap) retrieval fused by Reciprocal Rank Fusion, design
    §15.3's weighted ranking formula (level fit, quality, modality
    preference, relevance, duration fit, novelty, prior-failure penalty),
    and MMR-style same-provider-and-modality de-duplication. No resource is
    ever invented — every `resource_id` traces back to a real catalog row.
  - `service.py`: `ResourceRetrievalService` — the async DB-fetch +
    embedding-call orchestration around the pure core.
  - `link_validator.py`: the *live* half of design §15.2's "link validation
    job" (HEAD falling back to GET, `httpx.AsyncClient` injected for
    offline tests, same pattern as `github_client.py`); static URL
    well-formedness was already a build-time invariant (Phase 3).
- New `backend/app/core/thresholds.py` constants: `RESOURCE_RANK_WEIGHTS`,
  `RESOURCE_PRIOR_FAILURE_PENALTY`, `RESOURCE_QUALITY_TIER_BASE` +
  recency-window constants, `RRF_K`, `DEFAULT_SESSION_CAP_MINUTES`.
- New `CatalogRepository` methods: `get_resources_targeting_skill` (plain
  `Resource`/`ResourceSkill` join, dialect-portable) and
  `update_link_statuses` (bulk write for the link-validation job).
- New `backend/scripts/validate_links.py`: CLI entrypoint for the "runs
  before demo and nightly" link-validation sweep (mirrors
  `scripts/seed_catalog.py`).
- Added `backend/app/gateway/web_fallback_gateway.py` (design §14.3 point
  6's optional O4 fallback): same provider-agnostic shape as the
  LLM/Embedding/VLM Gateways, degrades to `fetched=False` (no results) with
  no provider configured (this project's permanent state). Never called
  automatically — a caller must opt in, since results are `unvetted` by
  construction and carry no `resource_id`.
- `ResourceRecommendation` (`backend/app/schemas/common.py`) got its real
  design §25.2 field list this phase.
- **Decided:** hybrid retrieval runs in pure Python over already-fetched
  rows, not via `CatalogRepository.search_resources_by_text`/
  `search_resources_by_vector` (Postgres-only, already documented as
  untestable under pytest) — see `docs/ARCHITECTURE_CONTRACTS.md` §15 for
  the full reasoning against design §14.3 point 3's literal wording.
- **Decided: no new API route.** Design §27's endpoint table has no row for
  the Resource Retriever/Ranker (Planner-internal); this phase adds none,
  matching that. `ResourceRetrievalService` is ready for the Planner (Phase
  5, not yet implemented) to call.
- 43 new backend tests: `tests/test_ranker.py` (25, hand-built fixtures —
  every eligibility rule, relevance/RRF normalization, every ranking
  component including modality preference and the prior-failure penalty,
  MMR duplicate removal and its fallback, the full pipeline's dedup/
  never-invents-a-resource-id/`top_k` guarantees), `tests/test_retrieval_service.py`
  (8, real curated dataset via `catalog_session`), `tests/test_link_validator.py`
  (8, `httpx.MockTransport`), `tests/test_web_fallback_gateway.py` (2,
  degrade path). **244 tests total, all passing** (201 from Phase 1-4, 43
  new).
- Updated `docs/ARCHITECTURE_CONTRACTS.md` §2, §6, §9, §12, §13, and a new
  §15 (this file's own numbering) covering every Phase 6 decision in full.
- **Not implemented this phase (out of scope, per design's phase
  ordering):** planning, assessment, reflection. Also not implemented: a
  real embedding/web-search provider (both gateways still degrade
  deterministically, this project's permanent state absent a configured
  provider); a `LearningActivity` table to source real `learner_history`
  from (Phase 7/8); wiring `LearningObjective.est_minutes_low/high` from
  real candidates (Phase 5, Planner); running the link-validation sweep
  against the live catalog this session (no network access in this
  environment).

---

## [Phase 4 | 2026-09-19] Skill-Gap Engine

- Added `backend/app/gap/engine.py` (design §12 naming convention,
  `gap/` package): `analyze_gaps(role_id, skill_records, evidence_records,
  graph)` — design §13.3's algorithm implemented close to verbatim, as a
  **pure function** (no DB/session, no gateway/agent import in the module —
  ARCHITECTURE_CONTRACTS.md §4: "100% deterministic... no LLM in the
  decision path"). Computes required level per scope skill, the tier-gated
  status (`MET`/`WEAK`/`UNVERIFIED`/`MISSING`), the `BLOCKED` overlay
  (`WEAK`/`MISSING` prerequisites block, `UNVERIFIED` does not — design
  §13.2), priority (`weight * (1 + log(1 + unmet_dependents))`) and
  topological ordering layers, the three design §12.4 audit flags
  (`claimed_without_evidence`, `stale_or_weak_evidence`,
  `claim_evidence_mismatch` — the last replicating the design's "Full Stack
  claimed, evidence only for React" example via real `PART_OF` umbrella
  skills), and `LearningObjective[]` (design §13.5) — `UNVERIFIED` gaps
  become `objective_type="probe"` (**verify-before-teach**, the phase
  brief's explicit requirement), never a beginner lesson.
- New level-threshold constants in `backend/app/core/thresholds.py`
  (`LEVEL_MASTERY_THRESHOLD`, `LEVEL_TIER_REQUIRED`, `LEVEL_MIN_N_OBS`) —
  ARCHITECTURE_CONTRACTS.md §3's tier gate, kept in one place per §14.
- Two new `SkillGraphService` methods (`backend/app/graph/queries.py`):
  `hard_prerequisite_out_edges` (min_level-aware, needed for §13.3's
  required-level formula) and `part_of_children` (needed for the
  claim-evidence-mismatch audit).
- Wired the NetworkX Skill Graph into `app/main.py`'s startup lifespan for
  the first time (cached on `app.state.skill_graph_service`, best-effort —
  an unseeded catalog degrades, doesn't fail startup); `app/api/deps.py`'s
  new `get_skill_graph_service` dependency reads that cache and falls back
  to a fresh per-request load when it's absent.
- Added `GET /api/learners/me/gaps` (`backend/app/api/v1/gap.py`, design
  §27): optional `?role=` override, defaults to the learner's
  `target_role_id`. A bare deterministic-service call, no LangGraph run.
  Returns full role-subgraph coverage (`gaps[]`, including `MET` entries),
  `strengths[]`, `audit_flags[]`, `objectives[]`, `layers[]`, and
  `prerequisite_edges[]` — the last two specifically so a frontend can
  render the gap graph.
- `SkillGap`/`LearningObjective` (`backend/app/schemas/common.py`) got their
  real design §25.2 field lists this phase, replacing the Phase 1
  `{id fields..., data: dict}` placeholders. New
  `backend/app/schemas/gap.py` for the response-only supporting types
  (`Strength`, `AuditFlag`, `GapGraphEdge`, `GapReport`).
- **Decided:** gap results are computed on demand, not persisted — no new
  migration this phase. See `docs/ARCHITECTURE_CONTRACTS.md` §4's "Decided
  (Phase 4)" entry for the reasoning against design §10.6's read/write
  matrix, and `docs/IMPLEMENTATION_STATE.md`'s Phase 4 "Architectural
  Decisions" for the rest of this phase's judgment calls (notably: this
  project's evidence-tier priors cap the mastery estimate at 0.4, below
  every level's `MET` threshold, so pre-assessment evidence lands `WEAK`
  at best until Phase 7's Mastery Updater exists — a faithful consequence
  of the tier-gate contract's fixed numbers, not a Gap Engine defect).
- 41 new backend tests: `tests/test_gap_engine.py` (29, mostly against the
  real curated dataset via `catalog_session`/`graph_service`, a few against
  a small hand-built `tiny_graph_service` fixture — built directly via
  `GraphLoader.build`, no DB — where the real data's incidental complexity,
  e.g. `skill.backpropagation` having three hard prerequisites rather than
  one, would make a single-variable assertion fragile), `tests/test_gap_api.py`
  (8, full HTTP-layer flow via the existing `app_client` fixture), plus 4 in
  `tests/test_graph_queries.py` for the two new `SkillGraphService` methods.
  **201 tests total, all passing** (160 from Phase 1-3, 41 new).
- Updated `docs/ARCHITECTURE_CONTRACTS.md` §3 (tier-gate implementation
  pointer + the mastery-priors nuance), §4 (Gap Engine implementation
  pointer + the no-persistence decision), §5 (two new graph-query methods;
  startup lifespan wiring, resolving a Phase 3 open item), and §6
  (`SkillGap`/`LearningObjective` now have real field lists).
- **Not implemented this phase (out of scope, per design's phase
  ordering):** planning, assessment, reflection. Also not implemented:
  `LearningObjective.est_minutes_low/high` (needs Phase 6's Resource
  Retriever), the `no_open_misconceptions_for(skill)` acceptance-criteria
  clause (needs a per-learner misconception status table), and the
  skill-dispute endpoint (design §12.4).

---

## [Phase 2 | 2026-09-19] Learner Profiling + Evidence Pipeline

- Added `backend/app/profiling/` (design §12 naming convention): document
  validation + text-first extraction (`document_parser.py`, PyMuPDF/
  python-docx/plain-text, design §22.1/§29 whitelist and size/page caps),
  PII scrubbing (`pii.py`), paragraph-boundary chunking with offsets
  (`chunker.py`, built/tested, not yet wired into the live pipeline —
  resume-scale text doesn't need it yet), prompt-injection pattern detection
  (`injection.py`, design §22.6), deterministic claim extraction + LLM
  prompt/parse helpers (`claim_extraction.py`), the Evidence Verifier
  (`evidence_verifier.py`: span fuzzy-match + recovery search, design
  §22.4/§22.5 tier assignment, injection flagging), the Skill Normalizer
  (`skill_normalizer.py`: exact alias -> embedding top-5 -> bounded small-LLM
  disambiguation -> unmapped), the `github_repo_summary` tool
  (`github_client.py`, design §26.2, metadata only), evidence commit
  (`commit.py`), and G1 orchestration glue (`onboarding.py`).
- Added `backend/app/gateway/vlm_gateway.py`: same provider-agnostic shape
  as the LLM/Embedding Gateways, degrades deterministically (no offline OCR
  stand-in exists, so this always resolves to design §30's "ask user to
  paste text" in this environment — documented, not a bug).
- Implemented the real Profiler Agent (`backend/app/agents/profiler.py`):
  LLM extraction (mid tier) retried up to 2x on schema failure
  (ARCHITECTURE_CONTRACTS.md §11), falling back to a catalog-anchored
  deterministic extractor whenever the gateway degrades or both retries
  fail. `LLM_PROVIDER=none` (this project's default) means the fallback
  path is what runs end to end in this environment and in tests.
- Implemented the real G1 Onboarding LangGraph
  (`backend/app/orchestration/graphs.py`'s `build_onboarding_graph`):
  `parse_documents -> extract_claims -> verify_evidence -> normalize_skills`,
  terminating at `status="needs_user"`. Does not include design's
  `user_confirm`/`gap_analysis` nodes — `gap_analysis` is out of this
  phase's scope, and `user_confirm` is a separate HTTP request rather than
  an in-graph pause (no Postgres-backed LangGraph checkpointer exists yet
  to resume a paused run — see Contract Changes below). One document per
  graph run/API call.
- Added Postgres tables for the learner overlay (`backend/app/db/models.py`,
  migration `0003_learner_profiling`): `LearnerProfile`, `Document`,
  `Evidence`, `LearnerSkillState` (design §28), plus `PendingClaim` — an
  addition beyond §28's list, the staging area described above.
- Added API routes (`backend/app/api/v1/learners.py`, design §27):
  `POST /api/learners` (intake), `POST /api/learners/me/documents`
  (multipart file or `github_url`), `GET /api/learners/me/claims/pending`,
  `POST /api/learners/me/claims/confirm`. `learner_id` always resolved from
  the session (`app/api/deps.py`'s new `get_current_learner_id`), never
  from the request body.
- **Bug found and fixed via real-Postgres verification** (not caught by the
  SQLite-backed automated suite, since SQLite doesn't enforce FKs by
  default): `LearnerProfile.user_id`'s FK to `users.user_id` failed because
  the dev-mode session fallback (`user_id="dev-user"`, Phase 1) has no real
  signup flow creating that row. Fixed with `UserRepository.get_or_create`
  (auto-provisions a minimal `User` row), called from the intake route.
  Added a regression test and re-verified end-to-end (intake -> upload ->
  confirm) against a real Postgres 16 + pgvector container.
- 106 new backend tests (160 total, all passing): document parsing (17),
  PII (5), injection detection (6), evidence verification (14), claim
  extraction (20), skill normalization (10, fully controlled stub
  gateways), the Profiler Agent (5), the GitHub tool (8, `httpx.MockTransport`,
  no live network calls), the full learners API through the real FastAPI
  app (11, new `app_client` fixture), evidence commit (9), plus 1
  `UserRepository.get_or_create` regression test.
- Added `pymupdf`, `python-docx` to `backend/pyproject.toml`. Added
  `GITHUB_TOKEN`, `DOCUMENT_STORAGE_DIR` to `.env.example`. Added
  `backend/storage/` to `.gitignore`.
- Updated `docs/ARCHITECTURE_CONTRACTS.md` §2 (Profiler Agent and the Skill
  Normalizer's small-LLM step are now implemented) and §9 (three additions
  to design §28's conceptual data model: `PendingClaim`, `Document.type`'s
  `"github"` value, and the `UserRepository.get_or_create` decision).
- **Not implemented this phase (explicitly out of scope, per the phase
  brief):** gap analysis, planning, assessment, reflection. Also not
  implemented: a Postgres-backed LLM Gateway replay cache (Phase 1's open
  item, now overdue since the Profiler is a real agent call), true
  multi-file document upload (one file per call currently), and wiring a
  shared startup-loaded graph/catalog cache (Phase 2's services build a
  fresh one per request — fine at this scale, a real cost at Postgres
  scale).

---

## [Phase 3 | 2026-09-19] Skill Graph + Catalog Engine

- Added Postgres tables for the curated Skill Graph and catalog
  (`backend/app/db/models.py`, migration `0002_skill_graph_catalog`):
  `Skill`, `SkillEdge`, `Role`, `RoleRequirement`, `Misconception`,
  `Resource`, `ResourceSkill`, `PracticeItem`, plus `GraphMeta` (an
  append-only graph-version history table — an addition beyond design §28's
  conceptual list; see `docs/ARCHITECTURE_CONTRACTS.md` §9). List-valued
  columns use generic `JSON` (not `ARRAY`) so the same model works against
  SQLite in tests; `Resource.embedding`/`Skill.embedding` use pgvector's
  `Vector(256)`. Migration also adds a generated `resources.search_vector`
  `tsvector` column with a GIN index (PostgreSQL FTS).
- `backend/app/graph/validation.py`: `GraphValidator`, a DB-independent port
  of `data/scripts/validate_dataset.py`'s checks (duplicate IDs, missing
  references, hard-prerequisite DAG cycle detection, orphan skills,
  role/resource coverage, misconception-ancestor consistency, item
  correctness, URL sanity) — runs inline during ingestion before anything is
  written.
- `backend/app/catalog/ingest.py` + `backend/scripts/seed_catalog.py`:
  `CatalogIngestor` loads `data/dataset/*.json`, validates, maps dataset
  field names to the ORM schema (documented per-field in `models.py`),
  computes resource embeddings, and replaces the entire catalog in one
  transaction, recording a `GraphMeta` row per run.
- `backend/app/gateway/embedding_gateway.py`: `EmbeddingGateway`, mirroring
  the LLM Gateway's shape — a deterministic, dependency-free fallback
  (feature-hashed, L2-normalized) used whenever `LLM_PROVIDER=none`, so
  ingestion and resource embeddings work fully offline and reproducibly.
- `backend/app/graph/loader.py`: `GraphLoader` builds one
  `networkx.MultiDiGraph` from the Postgres catalog holding all five
  closed-set node types and materializing all nine closed-set edge types
  (`PREREQUISITE_OF`, `PART_OF`, `REQUIRES`, `TARGETS`, `ASSESSES`,
  `MISCONCEPTION_OF`, `ROOTED_IN`, `REMEDIATED_BY`, `RELATED_TO`).
- `backend/app/graph/queries.py`: `SkillGraphService` — hard
  ancestors/descendants, direct prerequisites/dependents, DAG check,
  topological order/layers, role subgraph (required skills + prerequisite
  closure, raises `UnknownRoleError` for an uncurated role per
  ARCHITECTURE_CONTRACTS.md §5), prerequisite-path explanation (design
  §14.4's "chain rule → backpropagation → training neural networks"
  example), resource-targeting and misconception/remediation lookups.
- `backend/app/repositories/catalog_repository.py`: bulk `replace_all` write
  path plus read methods; `search_resources_by_text` (PostgreSQL FTS) and
  `search_resources_by_vector` (pgvector cosine distance) as
  retrieval-preparation primitives — Postgres-only, verified against a real
  Postgres 16 + pgvector container this session (migration
  upgrade/downgrade/re-upgrade, full 158-skill catalog seed, both search
  paths returning real results).
- 49 new backend tests (54 total, all passing): graph invariants (11,
  hand-built one-violation-per-test fixtures), catalog ingestion against the
  real domain pack (9), NetworkX graph loading — node/edge type completeness
  (5), graph queries against the real 158-skill/3-role graph (17), embedding
  gateway determinism (7). New `catalog_session` pytest fixture
  (`tests/conftest.py`) ingests the real dataset once per test.
- Added `networkx` to `backend/pyproject.toml` (design §34's graph engine).
- Updated `docs/ARCHITECTURE_CONTRACTS.md` §5 (Postgres tables + NetworkX
  loader now implemented, files named) and §9 (JSON-vs-ARRAY dialect
  decision; `GraphMeta` and extra-field additions to design §28's
  conceptual model, documented as additions, not contradictions).
- **Not implemented this phase (explicitly out of scope, per the phase
  brief):** the Gap Engine, Planner, any LLM agent, Reflection — this phase
  is deterministic graph/catalog infrastructure only. Also not implemented:
  the full resource-ranking formula (design §15.3), RRF fusion, MMR
  diversification (Resource Retriever/Ranker, Phase 6), and wiring the
  NetworkX loader into `app/main.py`'s startup lifespan (deferred to Phase
  4's first real caller, since no route reads the graph yet).

---

## [Phase 3 (data, partial) | 2026-09-19] Domain knowledge pack

- Created `data/` at the repo root — deliberately decoupled from
  `backend/app/`, per design §11.5 ("graph is curated offline") — as the
  canonical domain knowledge pack for the 3 supported roles (ML Engineer,
  Data Analyst, Backend Developer).
- `data/scripts/build_dataset.py`: stdlib-only Python script that is the
  source of truth for curated content (skills, roles, prerequisite graph,
  resources, misconceptions, assessment items, demo dataset), and generates
  `data/dataset/*.json`.
- `data/scripts/validate_dataset.py`: validates duplicate IDs, missing
  references, hard-prerequisite DAG-ness, orphan skills, role/resource
  coverage, misconception root-ancestor consistency, assessment item
  integrity, and resource URL well-formedness/domain reputation. Current
  pack validates with **0 errors, 0 warnings**.
- Content: 158 skills (6 non-assessable grouping skills), 3 roles (46/30/50
  required skills), 203 skill-to-skill edges (`PREREQUISITE_OF`/`PART_OF`/
  `RELATED_TO`), 140 curated resources (real URLs only — spot-checked live;
  fixed two discovered-stale domains, `linuxjourney.com` and `mode.com`,
  to their real current destinations), 18 misconceptions, 95 assessment
  items across 23 skills.
- Demo dataset (`data/dataset/demo/`) implements the design §38.1 "Asha"
  persona and the `Chain Rule → Backpropagation → Training Neural Networks`
  seeded path end-to-end: resume text, seeded learner skill state matching
  the §13.4 worked example (MET/UNVERIFIED/MISSING statuses with reasons),
  the `misc.chain_rule_sum` misconception, and a scripted-wrong-answer
  attempt configuration matching §38.2 step 8.
- `data/README.md` documents the pack's layout, regeneration/validation
  commands, link-validation approach, and — importantly — its **known scope
  decisions**: the item bank is an initial (not exhaustive) bank, no entry
  has had a human review pass yet, and nothing in this pack is loaded into
  Postgres or read by application code yet (that's remaining Phase 3/4
  work). See `docs/IMPLEMENTATION_STATE.md` "Domain Knowledge Pack" for the
  full breakdown.
- Updated `docs/ARCHITECTURE_CONTRACTS.md` §5 and §7: recorded the stable
  slug ID convention now in use for curated rows (`skill.*`, `role.*`,
  `res.*`, `misc.*`, `item.*`) and pointed to `data/` as where the curated
  source data lives.
- **No application workflow code was written this phase** — no graph loader,
  no Postgres migration for the graph/catalog tables, no consumption by any
  backend/frontend code. That is intentional per this phase's scope (data
  assets only); it's the first item in Phase 3's remaining/Phase 4's
  dependent work.

---

## [Phase 1 | 2026-09-19] Foundation layer

- Backend: FastAPI app with lifespan-gated startup (fails fast if LangGraph
  doesn't compile), pydantic-settings config, structured logging, global
  exception handlers, versioned API router, health endpoint, SSE run-events
  endpoint backed by an in-process trace bus.
- Database: async SQLAlchemy + Alembic; `0001_foundation` migration enables
  `vector`/`pg_trgm` extensions and creates `users`; `UserRepository` proves
  the data-access pattern.
- LLM Gateway interface: tiered request/response schemas, prompt-hash
  keying, in-memory replay cache, deterministic degradation when no provider
  is configured (`LLM_PROVIDER=none`).
- Orchestration: `RunState`/`RunCounters` typed state; a compiled two-node
  bootstrap LangGraph graph proving the framework works; placeholder
  builders for G1-G4 that name their owning phase.
- Agents: shared `Agent` interface plus one placeholder class per LLM agent
  (Profiler, Planner, Assessor, Reflection, Tutor), each raising
  `NotImplementedError` — no business logic, no tool access yet.
- Schemas: `AgentMessage` envelope, `TraceEvent`, and placeholder Pydantic
  models for all twelve core schema names in ARCHITECTURE_CONTRACTS.md §6.
- Frontend: Next.js 16 App Router shell (layout/nav, landing page, dashboard
  route with loading/error states) calling the backend's health endpoint
  live via a typed API client.
- Docker Compose (`postgres` + `api` + `web`); verified end-to-end this
  session — migration runs, `/api/health` returns `ok`, `/dashboard` returns
  200 — then torn down.
- Backend test suite (5 tests: health, DB round-trip, LangGraph init), all
  passing. Frontend `npm run build` passing.
- Decided (and recorded in `IMPLEMENTATION_STATE.md`): UUID v4 as
  `String(36)` for learner/run-scoped row IDs (ARCHITECTURE_CONTRACTS.md §7
  left this open for the implementer).
- **No business logic implemented** — no profiling, skill graph, gap
  analysis, planning, assessment, reflection, or tutor code, by design.

---

## [Phase 0 | 2026-09-19] Project initialization + engineering state protocol

- Read `docs/EduPath_System_Design.md` (v1.0, authoritative) in full.
- Created `docs/IMPLEMENTATION_STATE.md` as the canonical handoff file for future
  Claude Code sessions.
- Created `docs/ARCHITECTURE_CONTRACTS.md`, extracting stable contracts (evidence
  tiers, graph conventions, agent I/O schemas, API conventions, DB conventions,
  validator rules, naming conventions, security boundaries) directly from the
  design doc — no new contracts invented.
- Created root `README.md`.
- Initialized git repository; committed Phase 0 state.
- **No application code was written.** No agents, services, API routes, database
  schema, or frontend were implemented this phase, by design.
