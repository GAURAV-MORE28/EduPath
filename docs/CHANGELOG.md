# EduPath — Changelog

All notable changes to the EduPath project are recorded here, newest first.
This is an engineering changelog (what changed and why it matters for
implementation state), not a marketing changelog.

Format per entry: `## [Phase N | date] Short title` followed by a short bullet list.

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
