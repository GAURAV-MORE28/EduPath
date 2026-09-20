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
**Phase 5 — Personalized Learning Planner. Implemented** (Planner Agent in
draft/patch modes, deterministic Plan Validator V1-V10 plus two additive
checks, always-valid deterministic Fallback Planner, the G2 Planning
LangGraph, `POST /api/learners/me/plans` / `GET /api/learners/me/plans/current`).
Practice/assessment generation and Reflection-driven re-planning remain out
of scope, per design's phase ordering — this phase builds `patch_existing_plan`
as a capability for Reflection (Phase 8) to call later, without deciding
*when* a patch is warranted.
**Phase 8 — Assessment, Mastery, and Struggle Detection. Implemented**
(Assessor Agent with blind-solver-validated item generation, deterministic
MCQ grading + small-LLM short-answer rubric grading, the Beta-count Mastery
Updater, a deterministic six-class Struggle Classifier, and a scoped-down
deterministic misconception resolution loop — detected → remediation →
verification probe → resolved/persistent — that applies
`INSERT_REMEDIATION`/`ADD_PROBE` directly via `PlanningRepository` rather
than routing through the Planner Agent or the full Reflection Agent, which
remains out of scope). `POST /api/learners/me/practice` /
`POST /api/practice/{set_id}/submit`.
**Phase 9 — Reflection & Re-planning. Implemented** (design's "Phase 8", the
core differentiator: a real `ReflectionAgent` bounded to a closed six-operator
set — `INSERT_REMEDIATION`/`DEFER`/`REMOVE_DUPLICATE`/`REPLACE_RESOURCE`/
`ADD_PROBE`/`SPLIT_ACTIVITY` — a deterministic `ReflectionValidator` checking
root-cause/evidence/operator/plan validity, a deterministic root-cause +
operator policy that stands in for the LLM while `LLM_PROVIDER=none`, and a
layered fallback ladder ending in `app/assessment/resolution.py`'s original
narrower recipe, so a struggle submission can never leave the plan
half-applied. Writes `PlanRevision` + `ReflectionRecord` + `DecisionRecord`;
adds one-click Revert. `POST /api/practice/{set_id}/submit`'s response now
carries a `ReflectionOutcome` in place of Phase 8's narrower
`RemediationOutcome`; `POST /api/learners/me/plans/{plan_id}/revisions/{revision_id}/revert`
is new.
**Phase 10 — Tutor, Progress Reports and Provenance. Implemented** (design's
"Phase 9", this project's Phase 10: the fifth and last LLM agent, a
read-only `TutorAgent` with a nine-tool inventory; a real, bounded G4
LangGraph — `classify_intent -> plan_tools -> call_tools -> compose_answer
-> verify_citations -> [regenerate once] -> finalize/conservative`, every
node deterministic except `compose_answer`; `app/provenance/citations.py`'s
`verify_citations`; and a deterministic `Report Builder`
(`app/tutor/report_builder.py`) that buckets the Gap Engine's own
already-computed statuses into `ProgressReport`'s acquired/in-progress/
remaining-gaps/struggle-areas/next-steps — narrated but never computed by
an LLM). `POST /api/learners/me/chat`, `GET /api/learners/me/progress`,
`GET /api/decisions/{id}` are new. All five LLM agents now exist.

**Phase 11 — Premium Frontend + UX. Implemented** (this project's numbering;
a frontend-only phase plus small additive backend read endpoints and real trace
emission). Design toolchain established, design system "The Checked Set"
(`docs/FRONTEND_DESIGN_SYSTEM.md`), every journey screen built on real APIs,
Playwright + axe verification. See "Phase 11 — Frontend" under Completed Work and
ARCHITECTURE_CONTRACTS.md §20–§21.

**Phase 12 — Integration, Evaluation and Demo Hardening. Implemented** (final phase; no major
features). The whole system was driven end to end and hardened: persisted observability
(`AgentRun`/`AgentStep`, run ids on every response, `/api/runs`, `/api/metrics`), a durable
record/replay LLM Gateway that never raises (+ an Anthropic adapter), DEMO_MODE (seeded persona,
deterministic scripted struggle, rehearsal preflight), a single `JourneyDriver` used by the integration
test / smoke test / benchmark, automated evaluation (gold sets + independent oracles + simulated
learners), a security suite, deployment fixes, and real bugs found and fixed along the way. **The
consolidated status — features, measured results, limitations, demo/test/deploy commands — is
`docs/FINAL_IMPLEMENTATION_STATUS.md`.** `docker compose up --build` could **not** be verified end to
end this session (Docker Desktop's engine wedged); see that file's section 8.

**Phase 12b — Live provider integration. Implemented** (after Phase 12): Groq LLM (OpenAI-compatible adapter), Hugging Face
Qwen3-Embedding + VLM, Tavily web-search endpoint, GitHub token. `python scripts/live_smoke.py` passes 7/7 and the whole journey runs on live
models (8 LLM calls, 0 degraded on the user path). Running real models exposed and fixed Planner-constraint, Tutor-citation and context-size
problems (FINAL_IMPLEMENTATION_STATUS.md section 4b). Tests: 601. `LLM_PROVIDER=none` remains the default; the suite pins all providers to `none`.

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

The **Personalized Learning Planner** (Phase 5, design §16/§17) is now also
implemented: `PlannerAgent` (`backend/app/agents/planner.py`) proposes a
weekly plan (draft mode) or a revision (patch mode) from a pre-built,
ID-only candidate set (`backend/app/planning/candidates.py`, itself built
from the Gap Engine's `LearningObjective[]` and the Resource
Retriever/Ranker's `ResourceRecommendation[]`); a deterministic Plan
Validator (`backend/app/planning/validator.py`) enforces V1-V10 (design
§17.2) plus two additive checks from the phase brief; an always-valid
deterministic Fallback Planner (`backend/app/planning/fallback.py`) resolves
any plan the LLM path can't (no provider configured — this project's
default — or repeated validation failure). The G2 Planning LangGraph
(`backend/app/orchestration/graphs.py`'s `build_planning_graph`) wires
`build_objectives -> retrieve_candidates -> plan_draft -> validate_plan ->
[retry <= 2] -> fallback_plan`, deliberately without design's `critique`
node (Reflection, Phase 8, not implemented). `POST /api/learners/me/plans`
and `GET /api/learners/me/plans/current` (design §27) are the first real
callers of a single orchestrated flow spanning Phase 4 (Gap Engine), Phase 6
(Resource Retriever/Ranker), and this phase together. CLT/ZPD are treated as
pedagogical heuristics enforced in code (design §17.1's "honest framing"),
never presented as measured quantities.

### Completed Phases

| Phase (per design §39.1) | Status |
|---|---|
| 0 — Engineering state protocol | ✅ Done |
| 1 — Foundation (repo skeleton, Docker Compose, FastAPI, Postgres schema, LLM Gateway, Trace Emitter, Next.js shell) | ✅ Done |
| 2 — Learner profiling | ✅ Implemented (intake, document ingestion, Profiler Agent, Evidence Verifier, Skill Normalizer, human confirmation, GitHub metadata path). See "Completed Work" below. |
| 3 — Skill graph + catalog (critical path) | ✅ Implemented (Postgres tables, NetworkX loader, validation, versioning, traversal queries, catalog ingestion, resource embeddings + FTS index). Curated content itself still needs a human review pass (§11.5) before production gap analysis trusts it. |
| 4 — Gap analysis | ✅ Implemented (deterministic Gap Engine: statuses, prerequisite closure/ordering, BLOCKED overlay, priority, strengths, audit flags, learning objectives with verify-before-teach). See "Completed Work" below. |
| 5 — Planner | ✅ Implemented (Planner Agent draft/patch modes, deterministic Plan Validator V1-V10+, always-valid Fallback Planner, G2 Planning graph, `POST/GET /api/learners/me/plans*`). See "Completed Work" below. |
| 6 — Resource retrieval | ✅ Implemented (hybrid retrieval, deterministic ranking, MMR, link validation job). Landed ahead of Phase 5 at the operator's direction. See "Completed Work" below. |
| 7 — Practice + assessment | ✅ Implemented (Assessor Agent, MCQ + short-answer grading, Mastery Updater, Struggle Classifier, scoped-down deterministic resolution loop). Landed as this project's "Phase 8" per the operator's own numbering — see "Completed Work" below. |
| 8 — Reflection / re-planning (core differentiator) | ✅ Implemented (real `ReflectionAgent` bounded to a closed operator set, deterministic `ReflectionValidator`, deterministic root-cause/operator policy, layered fallback, `PlanRevision`/`ReflectionRecord`/`DecisionRecord`, one-click Revert). Landed as this project's "Phase 9" per the operator's own numbering — see "Completed Work" below. |
| 9 — Tutor | ✅ Implemented (read-only `TutorAgent`, nine-tool inventory, rule-based `classify_intent`/`plan_tools`, a real bounded G4 LangGraph, citation verification via the Provenance Service, a deterministic Report Builder). Landed as this project's "Phase 10" per the operator's own numbering — see "Completed Work" below. |
| 10 — Observability / evaluation / polish | ✅ Implemented (this project's Phase 12): persisted run/step trace + metrics, durable record/replay gateway, DEMO_MODE, integration + evaluation + security suites, deployment fixes. See `docs/FINAL_IMPLEMENTATION_STATUS.md`. |
| 11 — Frontend (this project's numbering) | ✅ Implemented (design toolchain, design system, all journey screens on real APIs, live SSE trace, Playwright/axe suite). See "Phase 11 — Frontend" below. |

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

**Phase 5 — Personalized Learning Planner** (design §16, §17, §20 (patch
mode only); ARCHITECTURE_CONTRACTS.md §10/§16; package `backend/app/planning/`,
already named in §12's convention list):

- **Candidate building** (`backend/app/planning/candidates.py`):
  `build_candidate_sets(gap_result, retrieval_service, catalog, ...)` — async
  orchestration turning the Gap Engine's `LearningObjective[]` (Phase 4) into
  one `ObjectiveCandidateSet` per objective: ranked, eligibility-filtered
  `ResourceCandidateInfo[]` (via `ResourceRetrievalService.recommend_for_skill`,
  Phase 6, resource metadata re-attached via a new
  `CatalogRepository.get_resources_by_ids` since the Ranker's own
  `ResourceRecommendation` deliberately carries only the ID/score) for
  `"lesson"` objectives, and curated `PracticeItem` IDs (a new
  `CatalogRepository.get_practice_items_for_skill(skill_id, purpose=...)`,
  `purpose="probe"` for verify-before-teach, `"practice"` otherwise) for
  both. An objective with nothing eligible gets an empty candidate set, not
  an error — this is what makes an "impossible candidate set" resolve to a
  valid (possibly empty) plan rather than a crash.
- **Planner Agent** (`backend/app/agents/planner.py`): real `PlannerAgent.run()`,
  two modes (`"draft"`/`"patch"`, design §8.2). Reads only the candidate ID
  set; the prompt/parse logic (`backend/app/planning/prompting.py`) rejects
  any resource_id/practice_item_id/objective_id not present in that set as a
  parse error (retried up to 2x with the error fed back, same policy as the
  Profiler Agent, ARCHITECTURE_CONTRACTS.md §11) — an invented ID is treated
  exactly like malformed JSON, never silently accepted
  (ARCHITECTURE_CONTRACTS.md §7). Unlike the Profiler, this agent does
  **not** embed its own deterministic fallback: on gateway degradation or
  exhausted retries it returns `degraded=True` with an empty item list, and
  the **G2 graph** (not the agent) decides whether to fall through to the
  separate `fallback_plan` node — matching design §9.4's table, which lists
  `plan_draft` and `fallback_plan` as distinct nodes.
- **Plan Validator** (`backend/app/planning/validator.py`): `validate_plan()`
  — a pure function implementing design §17.2's V1 (time budget), V2
  (referential integrity), V3 (prerequisite order — MET, or scheduled
  earlier, or an earlier probe for an `UNVERIFIED` prerequisite), V4
  (difficulty band), V5 (new-skill concurrency), V6 (session chunking, soft),
  V7 (practice pairing, soft), V9 (post-overload headroom, via
  `effective_budget_minutes`/`effective_new_skill_cap` — no overload-signal
  source exists yet, so `overload_active` is a caller-supplied flag, same
  "mechanism now, real source later" pattern Phase 6 used for
  `learner_history`), and V10 (guidance fading, soft — level-0 skills'
  resource item scheduled no later than its practice item). V8 (struggle
  follow-up) has no data source yet (no per-learner `StruggleSignal` exists,
  Phase 8/9) and is effectively a no-op pending that table. Two additive
  checks from the phase brief, not literally in design §17.2:
  `V_no_unjustified_duplicates` (hard — no two items share the same
  `(skill_id, resource_id)` pair unless `type == "review"`) and
  `V_required_objective_coverage` (soft, deliberately not hard — a
  genuinely impossible candidate set can make 100% coverage unreachable for
  *any* planner).
- **Fallback Planner** (`backend/app/planning/fallback.py`):
  `build_fallback_plan()` — design §16.4's greedy, priority-then-topological-
  layer frontier walk, pure and templated ("no LLM narration" — design's
  `plan_with_generic_reasons()`). Always produces a plan that passes every
  hard validator rule (verified directly in `tests/test_fallback_planner.py`
  by re-running `validate_plan` against its own output, not just asserting
  on item counts) — ARCHITECTURE_CONTRACTS.md §10's "a demo/run can never
  fail to produce a plan."
- **G2 Planning graph** (`backend/app/orchestration/graphs.py`'s
  `build_planning_graph`, replacing the Phase 1 placeholder): a real 5-node
  LangGraph — `build_objectives -> retrieve_candidates -> plan_draft ->
  validate_plan -> [conditional: pass -> END; LLM degraded -> fallback_plan;
  still failing and `planner_attempts < PLANNER_MAX_DRAFT_ATTEMPTS (2)` ->
  loop to plan_draft; else -> fallback_plan] -> fallback_plan -> END`.
  Deliberately excludes design's `critique` node (Reflection mode a) —
  Reflection is Phase 8, not implemented — and does not write to Postgres
  itself; like G1 Onboarding before it, the graph finalizes an in-memory
  result (`state["data"]["final_items"]`/`final_overall_reason"`/
  `"final_degraded"`) and the actual `WeeklyPlan`/`PlanRevision`/`PlanItem`
  persistence is orchestration glue outside the graph
  (`backend/app/planning/service.py`), mirroring Phase 2's `PendingClaim`
  hand-off (no Postgres-backed LangGraph checkpointer exists to hold
  in-flight state across a DB-writing node).
- **Orchestration glue** (`backend/app/planning/service.py`): `create_plan()`
  (draft mode — `POST /api/learners/me/plans`'s implementation) and
  `patch_existing_plan()` (patch mode — the capability Reflection, Phase 8,
  will later call; this phase does not itself decide *when* a patch is
  warranted). Both build the per-run `LearnerSkillRecord`/`EvidenceRecord`
  lists (same shape the `/gaps` route already builds, Phase 4), run the G2
  graph, and persist a new `PlanRevision` (`revision_no` incremented per
  plan) plus its `PlanItem` rows. `dry_run=True` (design §16.5's optional O1)
  runs the same graph but writes nothing, returning a synthetic
  non-persisted `plan_id`.
- **Postgres schema** (`backend/app/db/models.py`, migration `0004_planner`):
  `WeeklyPlan`, `PlanRevision`, `PlanItem` (design §28), with one addition:
  `PlanItem.practice_item_ids` (JSON list) instead of design's single
  `practice_ref?` — no `PracticeSet` generation service exists yet (design
  §18, Assessor, Phase 7 in this project's numbering). Verified against a
  real Postgres 16 + pgvector container this session: upgrade, downgrade,
  re-upgrade all ran clean, and a full intake -> create-plan -> get-current
  round trip was run through the actual FastAPI app (not just SQLite),
  returning a real catalog `resource_id` in the fallback-resolved plan.
- **API routes** (`backend/app/api/v1/plans.py`, design §27):
  `POST /api/learners/me/plans` (`{week_index?, dry_run?, hours?}`, reads
  `role_id`/`weekly_hours`/`preferences` from the learner's own profile,
  never from the request body) and `GET /api/learners/me/plans/current`.
  `learner_id` always resolved from the session
  (`get_current_learner_id`), matching every other learner-scoped route.
  **`patch_existing_plan` is deliberately not exposed via HTTP this
  phase** — design §27's patch/override endpoint
  (`POST /api/plans/{id}/override`) belongs to Reflection (Phase 8), which
  decides *when* a patch is warranted; this phase only builds the
  capability, tested directly at the service layer.
- **Schemas**: `WeeklyPlan`/`PlanItem` (`backend/app/schemas/common.py`) got
  their real design §25.2 field lists this phase (previously
  `{id fields..., data: dict}` placeholders); new `PlanItemReason` sub-model
  (design §16.6: every reason is ID-attached deterministically, only `text`
  is LLM-phrased/display-only). New `backend/app/schemas/planning.py` for
  the request-only `CreatePlanRequest`.
- **New `core/thresholds.py` constants**: `WEEKLY_BUDGET_SLACK`,
  `OVERLOAD_BUDGET_FACTOR`/`OVERLOAD_CONCURRENCY_REDUCTION`,
  `NEW_SKILL_CONCURRENCY_CAP`/`_NOVICE`, `SESSION_CHUNK_MAX_MINUTES`,
  `PROBE_ITEM_COUNT`/`PROBE_ITEM_MINUTES_PER_ITEM`,
  `PRACTICE_ITEM_MINUTES_PER_ITEM`/`PRACTICE_ITEMS_PER_LESSON`,
  `PLANNER_MAX_DRAFT_ATTEMPTS` — design §16-§17's tunable defaults, kept in
  one place per ARCHITECTURE_CONTRACTS.md §14.
- **A bug the integration test caught**: the first draft of
  `_persist_plan` (`app/planning/service.py`) never passed `item_id=item.item_id`
  when constructing each `PlanItemRow`, so every persisted row got a
  *different* auto-generated UUID than the one the API's immediate response
  carried — `GET /api/learners/me/plans/current` would then return a plan
  whose item IDs didn't match what `POST` had just returned. Caught by
  `tests/test_plans_api.py::test_get_current_plan_returns_the_created_plan`
  comparing the two response bodies' item ID sets; fixed by passing
  `item_id=item.item_id` explicitly. Re-verified against real Postgres too.
- **Tests**: 42 new — `tests/test_plan_validator.py` (17, hand-built
  `PlanItem`/`ObjectiveCandidateSet`/`SkillGapEntry` fixtures: a valid plan,
  every hard rule individually including a missing/unscheduled prerequisite
  and an unverified-prerequisite-satisfied-by-an-earlier-probe case, an
  out-of-scope-prerequisite simplification, `effective_budget_minutes`/
  `effective_new_skill_cap`'s slack/overload math), `tests/test_fallback_planner.py`
  (8, including re-validating the fallback's own output against
  `validate_plan` for the "impossible candidate set"/"insufficient time"/
  "new-skill-cap" cases — proving the "always valid" contract directly, not
  just item counts), `tests/test_planner_agent.py` (9, mirroring
  `test_profiler_agent.py`'s `ScriptedLLMGateway` pattern: degrade-to-empty,
  empty-candidate-sets-is-not-an-error, successful draft, invalid-JSON retry,
  **an invented resource_id rejected exactly like invalid JSON**, mid-stream
  degrade, and two patch-mode tests), `tests/test_planning_integration.py`
  (2, against the real curated dataset via `catalog_session`: a full
  Gap-Engine-through-Fallback-Planner run producing a real
  `skill.backpropagation` verify-before-teach probe from the real item bank,
  and a real-session `create_plan` -> `patch_existing_plan` round trip
  producing `revision_no` 1 then 2 on the same `plan_id`),
  `tests/test_plans_api.py` (6, full HTTP-layer flow via `app_client`:
  requires-intake-first, a valid committed plan within budget, GET current
  matching what POST returned, dry-run writes nothing, an hours override is
  respected). **286 tests total, all passing** (244 from Phase 1-4/6, 42
  new).

**Phase 8 — Assessment, Mastery, and Struggle Detection** (design §10.4,
§18, §19, §20.8; ARCHITECTURE_CONTRACTS.md §17; package `backend/app/assessment/`,
already named in §12's convention list):

- **Mastery Updater** (`backend/app/assessment/mastery.py`): `update_mastery()`
  — a **pure function** (no DB/gateway import) implementing design §10.4's
  Beta-count formula verbatim (`α += w` on correct, `β += w` on incorrect,
  difficulty-weighted `{easy: 0.7, medium: 1.0, hard: 1.3}`, reversed for
  incorrect since "missing an easy item is more informative of weakness").
  Starts from an uninformative `Beta(1, 1)` prior when no evidence-tier
  state exists at all; otherwise accumulates on top of whatever `alpha`/
  `beta` a prior E0-E2 claim already seeded — deliberately **not** the same
  reseed-on-tier-upgrade rule `EvidenceCommitService` (Phase 2) uses, since
  assessed items are meant to accumulate continuously, not reset a prior.
  Any assessed item permanently sets `tier_max = "E3"` (assessed evidence
  is always the strongest tier). `compute_band`/`compute_confidence`
  implement design §10.4's band table (Learning/Developing/Proficient, with
  a "mastery high but n_obs too low" case explicitly falling back to
  Developing rather than promoted early) and the n_obs-based confidence
  buckets (a "consistency across items" component design also mentions is
  a documented simplification, not implemented — no per-item history is
  available to a pure function without breaking its no-DB shape).
  **Mastery is always returned as an estimate** — `MasteryOutcome` carries
  `band`/`confidence` alongside the raw numbers, never a bare "ground
  truth" figure, per the phase brief's explicit instruction.
- **Struggle Classifier** (`backend/app/assessment/struggle.py`):
  `classify_struggle()` — a **pure function**, same "unit-testable with
  hand-built fixtures" shape as `app/gap/engine.py`/`app/retrieval/ranker.py`/
  `app/planning/validator.py`. Implements all six design §19.2 classes:
  `low_score`, `repeated_misconception` (suspected on one distinct item,
  confirmed on >= 2 within a 14-day window, tracked across separate
  submissions via a real query over assessment history, not just the
  current attempt), `missing_prerequisite` (confirmed by a failing direct
  probe/prereq-block score, or medium-confidence "attribution only" via a
  misconception's `ROOTED_IN` skill), `excessive_difficulty` (requires
  prerequisites MET and no repeated misconception already explaining the
  errors), `cognitive_overload` (requires >= 2 independent corroborating
  signals — planned-vs-actual ratio, completion rate, self-report, rising
  retries, too-many-new-skills — "time alone is insufficient" per design
  §19.1/§19.5 and the phase brief's explicit instruction), and
  `insufficient_practice` (low mastery, `n_obs < 4`, errors *not*
  concentrated on one misconception tag). Multiple classes can fire from
  one submission; `primary_signal()` applies design §19.2's precedence
  order (misconception > prerequisite gap > difficulty mismatch > overload
  > insufficient practice > low score) only among medium/high-confidence
  signals (design §19.3: "low or suspected -> schedule_probe", not a
  routing trigger).
- **Grading** (`backend/app/assessment/grading.py`): `grade_mcq()` —
  deterministic, re-derives `correct`/`misconception_id` from the stored
  `PracticeItem.options[chosen_option]` (the client-supplied index is
  server-side-checked, the key/tags themselves never sent to the client,
  design §18.3); `grade_short_answer()` — small-tier LLM, temperature 0,
  rubric-based, degrades to `correct=None`/`confidence="low"` (never a
  guessed pass/fail) when no provider is configured or the response is
  unparsable, matching design §18.1's "low-confidence grades flagged."
- **Assessor Agent** (`backend/app/agents/assessor.py`,
  `backend/app/assessment/prompting.py`): real `AssessorAgent.run()` —
  item generation (strong tier) with every distractor tagged to a
  catalogued `Misconception` ID or `None` (an invented tag is rejected at
  parse time exactly like the Planner's invented resource-ID rejection,
  ARCHITECTURE_CONTRACTS.md §7), retried up to 2x on schema/tag-validation
  failure; every generated item then blind-solver-validated (small tier,
  design §18.2 point 4 — a small model answers without the key and must
  select it, or the item is dropped, never trusted). No offline generation
  stand-in exists (unlike the Profiler's deterministic fallback or the
  Planner's Fallback Planner graph node) — item-bank-first still works
  fully offline; only generate-if-short needs a real provider.
- **Practice-set assembly** (`backend/app/assessment/item_bank.py`):
  `assemble_practice_set()` — design §18.2's item-bank-first (excluding
  previously *submitted* items), generate-if-short (persists validated
  generated items into the same global `PracticeItem` bank curated content
  lives in, with `generated_by="assessor-llm"`/`validated_by="blind-solver"`
  provenance), and the prerequisite-block rule (an `UNVERIFIED` hard
  prerequisite gets >= 2 appended items on that prerequisite, so one
  sitting can distinguish "missing prerequisite" from "missing knowledge of
  this skill" — design §13.4's demo chain). Also handles `purpose ==
  "resolution-check"` sets (tries to find bank items tagged to the specific
  misconception being verified, falling back to any resolution-check item
  for the skill).
- **Misconception resolution** (`backend/app/assessment/resolution.py`):
  a deterministic state machine — `suspected`/`confirmed` (from a
  `repeated_misconception` signal) -> `remediating` (`start_remediation`,
  triggered only by a *confirmed*, high-confidence signal) ->
  `resolved`/`persistent` (`record_probe_result`, design §20.8: pass ->
  resolved; fail -> a second cycle; two failed cycles -> persistent,
  "does not loop indefinitely"). `start_remediation` looks up real
  `REMEDIATED_BY` resources via `SkillGraphService.remediation_resources_for_misconception`
  (never an LLM pick) and, when the learner has an active plan, inserts a
  new `PlanRevision` directly via `PlanningRepository` — carrying forward
  every item from the current revision plus a `review` item for the
  remediation resource and a `probe` item for the resolution-check set
  (design §20.5's `INSERT_REMEDIATION`/`ADD_PROBE` operators, applied
  deterministically rather than through the Planner Agent, since neither
  operator needs an LLM once the trigger has already fired). A cooldown
  (24h, design §19.4) prevents re-triggering remediation for the same
  misconception mid-cycle; an already-`persistent` misconception is never
  re-remediated. **Explicitly not the Reflection Agent** — see
  ARCHITECTURE_CONTRACTS.md §17 for the full scope-boundary reasoning.
- **Orchestration** (`backend/app/assessment/service.py`): `create_practice_session()`
  (design §27's `POST /api/learners/me/practice`) and `submit_practice_set()`
  (`POST /api/practice/{set_id}/submit`) — design §9.5's G3 Evidence-Response
  scoped to this phase: `record_evidence -> grade -> update_mastery ->
  detect_struggle -> route`, where `route` only ever triggers the
  deterministic remediation path above for a confirmed misconception (the
  full `reflect` node — LLM root-cause synthesis — is out of scope). Also
  writes one `Evidence` row per skill touched (tier `E3`, `source_type=
  "assessment"`) so assessed evidence stays queryable through the same
  provenance path Phase 2 established.
- **Postgres schema** (`backend/app/db/models.py`, migration
  `0005_assessment`): `PracticeSession` (addition beyond design §28 — the
  server-side staging record between assembling and submitting a set, same
  shape as Phase 2's `PendingClaim`), `Assessment`, `StruggleSignal`,
  `LearnerMisconception` (design §28, the last with an added
  `remediation_cycles` field). Verified against a real Postgres 16 +
  pgvector container this session: `alembic downgrade base` +
  `upgrade head` round-tripped clean (through all five migrations, not
  just this one), and a full intake -> create-practice-set -> submit
  round trip on real `skill.chain_rule` items was run through the actual
  FastAPI app, correctly triggering deterministic remediation with real
  `misc.chain_rule_sum` remediation resources
  (`res.khan_diff_calc`/`res.3b1b_calculus`/`res.cs231n_backprop`) once 2
  distinct wrong-tagged items were submitted.
- **API routes** (`backend/app/api/v1/practice.py`, design §27):
  `POST /api/learners/me/practice` (`{skill_id, purpose?}` — `skill_id` is
  required here; design leaves it optional for a "whatever's due" default
  this project doesn't implement) and `POST /api/practice/{set_id}/submit`
  (`{answers[], time per item, optional self-reported overload signals}`).
  Response items never carry `is_key`/`misconception_id` (design §18.3);
  the submit response's per-item `correct`/`misconception_id` is the
  server's graded verdict, not an echo of client input. `learner_id`
  always session-derived. No route for `record_probe_result` — a
  resolution-check submission's outcome is inferred automatically inside
  `submit_practice_set` from `PracticeSession.purpose`.
- **Schemas**: `AssessmentResult`/`StruggleSignal` (`backend/app/schemas/common.py`)
  got their real design §25.2 field lists this phase (previously
  `{id fields..., data: dict}` placeholders), plus a new
  `AssessmentItemResult` sub-model. New `backend/app/schemas/assessment.py`
  for the practice-set/submit request/response shapes.
- **New `core/thresholds.py` constants**: `MASTERY_CORRECT_WEIGHTS`/
  `MASTERY_INCORRECT_WEIGHTS`/`MASTERY_DEFAULT_PRIOR`/
  `MASTERY_CONFIDENCE_*_MAX_N_OBS`, `PRACTICE_SET_TARGET_SIZE`/
  `PRACTICE_SET_PREREQ_BLOCK_MIN_ITEMS`/`ASSESSOR_MAX_RETRIES`,
  `LOW_SCORE_*`/`REPEATED_MISCONCEPTION_*`/`MISSING_PREREQUISITE_*`/
  `EXCESSIVE_DIFFICULTY_*`/`DIFFICULTY_LABEL_TO_LEVEL`/`OVERLOAD_*`/
  `INSUFFICIENT_PRACTICE_MAX_N_OBS`, `STRUGGLE_REVISION_COOLDOWN_HOURS`,
  `MAX_REMEDIATION_CYCLES` — design §10.4/§18/§19/§20.8's tunable
  defaults, kept in one place per ARCHITECTURE_CONTRACTS.md §14.
- **Small addition to `app/gap/engine.py`**: `current_level_for`/
  `mastery_estimate_for`, public wrappers around the module's previously
  private `_current_level`/`_mastery_estimate` helpers, so Phase 8 (level
  labels for generation prompts, `StruggleContext.current_level`) reuses
  the exact same tier-gate math instead of re-deriving it.
- **A curated-data quirk found via real-catalog testing (not a code
  bug):** several `skill.chain_rule` items in `data/dataset/assessment_items.json`
  have their *correct* (`is_key: true`) option also carrying a
  `misconception_id` tag (e.g. `item.chain_rule.2`'s key option is tagged
  `misc.chain_rule_sum`) — almost certainly an authoring artifact, since a
  misconception tag is only meaningful on a wrong answer. `grade_mcq`
  already nulls out any tag on a correct answer regardless
  (ARCHITECTURE_CONTRACTS.md §17), so this has no behavioral effect, but it
  is worth folding into Phase 3's still-outstanding human review pass (see
  "Domain Knowledge Pack" below) rather than trusted as intentional.
- **A re-ingestion ordering issue surfaced by having real Phase 5/8 data
  in the same database as a catalog re-seed:** `CatalogRepository.replace_all()`
  (Phase 3) does `DELETE FROM resources`/`skills`/etc. before re-inserting —
  this now fails with a foreign-key violation if any learner-scoped row
  (`plan_items.resource_id`, `evidence.skill_id`, `assessments.skill_id`,
  ...) references a catalog row, which is true the moment *any* real
  learner has ever used the system against that database. Worked around
  this session by resetting the dev Postgres schema (`alembic downgrade
  base` + `upgrade head`) before reseeding rather than changing
  `replace_all` itself — re-seeding a catalog underneath real learner data
  was never this method's designed use case (Phase 3: "the curated graph is
  versioned and reloaded whole per ingestion run", written before any
  learner-scoped FK existed). Flagged here rather than "fixed" since
  changing `replace_all`'s transaction shape is a real design decision
  (cascade? block? migrate learner rows to new IDs?) outside this phase's
  scope — see "Known Issues" below.
- **Tests**: 89 new — `tests/test_mastery.py` (15: the Beta-count formula
  including the reversed incorrect-weight table, accumulation vs. reseed,
  the band table's "high mastery, low n_obs falls back to Developing" case,
  confidence buckets), `tests/test_struggle_classifier.py` (35: every one
  of the six classes individually — including the "time/retries alone
  never trigger overload" case the phase brief explicitly called for —
  plus cross-class exclusion rules, multi-signal firing, and precedence),
  `tests/test_grading.py` (8: MCQ determinism including an out-of-range
  index, short-answer degrade/success/unparsable), `tests/test_assessor_agent.py`
  (6, mirroring `test_profiler_agent.py`'s `ScriptedLLMGateway` pattern:
  degrade, successful generation + blind-solver pass, blind-solver
  rejection without failing the run, an invented misconception_id retried
  and rejected, retry exhaustion), `tests/test_resolution.py` (14, a small
  hand-built graph fixture mirroring `test_gap_engine.py`'s
  `tiny_graph_service`: status upsert/no-downgrade, remediation-resource
  lookup, plan-revision insertion carrying forward prior items, cooldown,
  persistent-skip, probe pass/fail/two-cycles-persistent),
  `tests/test_assessment_integration.py` (4, against the real curated
  dataset via `catalog_session`: item-bank assembly with graceful
  generation degrade, a real confirmed-misconception ->
  real-remediation-resources round trip on `skill.chain_rule`/
  `misc.chain_rule_sum`, correct answers never triggering remediation, real
  `LearnerSkillState` mastery updates), `tests/test_practice_api.py`
  (7, full HTTP-layer flow via `app_client`: requires-intake-first, no
  keys/tags leak to the client, unknown skill/set_id rejection, a full
  round trip, seen-item exclusion behavior before/after a submission).
  **375 tests total, all passing** (286 from Phase 1-6, 89 new).

**Phase 9 — Reflection & Re-planning** (design §20, §21, §25.2, §28; this
project's own numbering — design calls this "Phase 8", the core
differentiator; package `backend/app/reflection/`):

- **Closed operator set** (`backend/app/reflection/operators.py`): the Phase
  9 brief's own six-operator vocabulary — `INSERT_REMEDIATION`, `DEFER`,
  `REMOVE_DUPLICATE`, `REPLACE_RESOURCE`, `ADD_PROBE`, `SPLIT_ACTIVITY` —
  deliberately used verbatim instead of design §20.5's seven-operator set
  (`SWAP_RESOURCE`/`ADD_PRACTICE`/`REDUCE_LOAD`/`REORDER`), which the brief
  explicitly supersedes for this phase. `apply_operators()` is a **pure
  function** over `app.schemas.common.PlanItem` (no DB/gateway import) so its
  output re-validates directly against the existing Plan Validator
  (`app/planning/validator.py::validate_plan`) — untouched items are always
  carried forward unchanged (design §20.7), nothing is silently dropped
  except via an explicit `REMOVE_DUPLICATE`.
- **Evidence bundle** (`backend/app/reflection/evidence.py`): `EvidenceBundle`
  — struggling skill, the triggering `StruggleSignalEntry`, all of this
  submission's signals (so a co-occurring `missing_prerequisite` signal is
  visible even when `repeated_misconception` is the trigger — the wow
  scenario's combo), misconception linkage, hard-ancestor gap statuses, the
  current plan's items, and the learner's own assessment-item-ID universe
  (design §20.6 check 2's "evidence belongs to this learner").
- **Deterministic root-cause + operator policy** (`backend/app/reflection/deterministic.py`):
  what actually runs end to end in this environment, since `LLM_PROVIDER=none`
  is this project's permanent default (every prior phase's agent degrades
  the same way) — root cause is read straight off the struggle signal
  (`missing_prerequisite`'s named prerequisite) or the curated graph (a
  confirmed misconception's `ROOTED_IN` skill), never inferred by an LLM
  (ARCHITECTURE_CONTRACTS.md §7), across all four of design §20.2's trigger
  classes (`repeated_misconception`/`missing_prerequisite`/
  `excessive_difficulty`/`cognitive_overload`, this project's names for
  design's misconception_confirmed/prerequisite_gap/difficulty_mismatch/
  overload).
- **Reflection Agent** (`backend/app/agents/reflection.py`, real
  implementation replacing the Phase 1 placeholder): strong-tier LLM,
  strict JSON parsing against a pre-resolved candidate ID set
  (`backend/app/reflection/prompting.py`, mirrors
  `app/planning/prompting.py`'s pattern) — it may never invent a skill/
  resource/practice-item ID, only choose among IDs the deterministic
  root-cause step already resolved. Retries up to `REFLECTION_MAX_ROUNDS`
  (2) with the validator's rejection reasons fed back, then degrades —
  exercised in tests via a scripted stub gateway (this project's real state
  never has a provider configured).
- **Reflection Validator** (`backend/app/reflection/validator.py`):
  deterministic, design §20.6's five checks in order — root cause exists and
  is the struggling skill or a hard-prerequisite ancestor; every
  `evidence_ids` entry belongs to this learner and overlaps the triggering
  signal's own evidence; `root_cause_class` agrees with the classifier's
  class (on conflict, the classifier wins — a mismatch is rejected, not
  silently overridden); every operator is from the closed set with
  structurally valid parameters; and, after applying the operators, the
  existing Plan Validator reports no hard violations. A permissive
  candidate-set shim makes V2 (referential integrity, a Planner-candidate-set
  concept that doesn't apply to a graph/catalog-ID-anchored patch) a no-op
  here while every other V-rule stays fully enforced.
- **Orchestration** (`backend/app/reflection/service.py::run_reflection`):
  cooldown check (misconception-specific via `LearnerMisconception.last_remediated_at`,
  or a new `ReflectionRepository.last_reflection_at_for_skill` for
  non-misconception triggers) → evidence bundle → agent round loop → on
  agent failure/degrade, the deterministic policy → on *that* failing hard
  validation (defensive), a last-resort minimal patch (`app/assessment/resolution.py`'s
  original `INSERT_REMEDIATION`+`ADD_PROBE`-only recipe, now demoted to this
  role) → commit `PlanRevision`+`PlanItem`s (carrying every prior item
  forward under a **fresh** `item_id`, since it's a global primary key, not
  scoped per revision — the same reason `resolution.py`'s own carry-forward
  already did this) + `ReflectionRecord` + `DecisionRecord` (graph path,
  rules fired, `graph_version`) + misconception status transition. If even
  the last-resort patch fails hard validation, the plan is left **unchanged**
  and a `ReflectionRecord(validated=False)` records the attempt with
  `needs_attention=True` — design §20.7's explicit failure behavior, never a
  half-applied plan. `app/assessment/resolution.py` itself is untouched;
  its probe-result/cooldown helpers are still the ones used directly.
  `app/assessment/service.py::submit_practice_set`'s routing now calls this
  instead of `resolution.start_remediation` directly, for all four of design
  §20.2's trigger classes (previously: `repeated_misconception`-confirmed
  only).
- **Postgres schema** (`backend/app/db/models.py`, migration
  `0006_reflection`): `ReflectionRecord`, `DecisionRecord` (design §28).
- **Schemas**: `ReflectionResult` (`backend/app/schemas/common.py`) got its
  real design §25.2/§20.4 field list this phase (previously
  `{reflection_id, learner_id, operators}`); `backend/app/schemas/assessment.py`'s
  `RemediationOut` is replaced by the richer `ReflectionOut` (root cause,
  operators, `needs_attention`, `degraded`, `rounds`, explanation) —
  `SubmitPracticeResponse.reflection` replaces `.remediation`.
- **API**: `POST /api/practice/{set_id}/submit` now returns `reflection`
  instead of `remediation`. New:
  `POST /api/learners/me/plans/{plan_id}/revisions/{revision_id}/revert`
  (design §20.7's one-click Revert — `app/reflection/service.py::revert_to_previous_revision`;
  only the plan's *current* revision may be reverted, restoring its parent
  revision's content as a new revision and marking the reverted one's
  `PlanRevision.reverted_by`). `patch_existing_plan` (Phase 5) is still not
  exposed via HTTP — Reflection applies its own operator pipeline directly
  rather than routing through it (see "Architectural Decisions").
- **G3 Evidence-Response**: still not a LangGraph — `build_evidence_response_graph()`
  (`app/orchestration/graphs.py`) remains a documented placeholder;
  `app/assessment/service.py` (record_evidence through route) and
  `app/reflection/service.py` (reflect through commit) implement the whole
  pipeline as plain async orchestration instead, for the same reason Phase 8
  already gave: each step needs a DB write the next step's read depends on,
  and no Postgres-backed LangGraph checkpointer exists to pause a graph
  mid-run for that.
- **Tests**: 31 new — `tests/test_reflection_operators.py` (14: every
  operator individually against hand-built `PlanItem` fixtures, including
  DEFER's day-slot cap and never-moves-a-done-item rules, and a full
  multi-operator sequence), `tests/test_reflection_validator.py` (11, a
  small hand-built graph fixture mirroring `test_resolution.py`'s: every one
  of the five checks individually, including root-cause-is-self vs.
  ancestor, evidence ownership/overlap, classifier-wins-on-conflict, and the
  resulting-plan-must-validate check), `tests/test_reflection_agent.py` (4,
  mirroring `test_planner_agent.py`'s `ScriptedLLMGateway` pattern:
  degrade-to-None, a valid draft, an invented root-cause skill_id rejected
  and retried, retry exhaustion), `tests/test_reflection_service.py` (2,
  against the real curated dataset via `catalog_session` — **the Phase 9
  wow scenario end to end**: a scripted chain_rule/backpropagation
  misconception + prerequisite-block submission → `repeated_misconception`
  confirmed + `missing_prerequisite` both detected → root cause
  `skill.chain_rule` → operators exactly matching
  `data/dataset/demo/demo_scenario.json`'s `expected_reflection_operators`
  (`INSERT_REMEDIATION`/`DEFER`/`ADD_PROBE`) → a validated `PlanRevision`
  that defers the existing `skill.backpropagation` item and inserts a real
  curated chain_rule remediation resource + resolution-check probe →
  `ReflectionRecord`/`DecisionRecord` written with the real graph path; plus
  a cooldown test. `tests/test_assessment_integration.py`'s misconception
  test was updated in place for the `reflection`-field rename (root cause ==
  struggling skill there, so no `DEFER` — an intentional, asserted
  contrast with the wow scenario's cross-skill case).
  **406 tests total, all passing** (375 from Phase 1-8, 31 new).

**Phase 10 — Tutor, Progress Reports and Provenance** (design §8.2, §9.6,
§14.5, §23, §24, §25.2, §27; ARCHITECTURE_CONTRACTS.md §2, new §19; this
project's own numbering — design calls this "Phase 9"):

- **Tutor Agent** (`backend/app/agents/tutor.py`, real, replacing the Phase
  1 placeholder): `compose_answer` only — strong-tier LLM, strict JSON
  `{answer, citations}` parsing (`app/tutor/prompting.py`), retried on
  malformed JSON up to 2× then degrades. Deliberately does **not** itself
  check whether a citation exists (see "Architectural Decisions" below) —
  that is the Provenance Service's job, one layer up.
- **Tool inventory** (`backend/app/tutor/tools.py`): the nine read-only
  tools design §26.2/§8.2 name for the Tutor — `get_learner_state`,
  `get_gaps`, `get_current_plan`, `get_revisions` (design's
  `get_plan_revisions`), `get_evidence`, `explain_skill_path`,
  `search_resources`, `get_progress`, `get_decision`. Every tool returns a
  `ToolCallResult{data, citable_ids}`; `citable_ids` is always copied from
  real rows/graph nodes the call just read — no tool can invent an ID
  (ARCHITECTURE_CONTRACTS.md §7), and none has any side effect
  (`commit_*` tools are never in this inventory, §13). A tool given a bad
  argument (e.g. a hallucinated `skill_id`) returns an error-flagged, empty
  result rather than raising — a chat turn can never crash on a bad tool
  call.
- **Intent classification and tool planning** (`backend/app/tutor/intent.py`):
  rule-based `classify_intent`/`plan_tools` implementing design §23.1's
  question-type -> tools table (`current_skills`/`gaps`/`plan`/
  `why_recommended`/`why_changed`/`concept_explanation`/`progress`/
  `out_of_scope`). Chosen over an LLM-driven tool loop specifically so the
  phase brief's "maximum tool steps must be bounded" holds by construction
  (see "Architectural Decisions"). Skill mentions in free text are matched
  via the same word-boundary, catalog-anchored literal scan
  `app/profiling/claim_extraction.py`'s `DeterministicClaimExtractor`
  (Phase 2) already established — `ChatRequest.skill_id_hint`/
  `decision_id_hint` let a real UI's "Why?" drawer (design §24.3) skip the
  text-scan step entirely by supplying the ID it already knows.
- **Citation verification** (`backend/app/provenance/citations.py`):
  `verify_citations(cited_ids, valid_ids)` — a pure function checking every
  ID an answer cites was actually surfaced by this turn's own tool calls
  (design §14.5). Called by the G4 graph's `verify_citations` node, not
  folded into the agent's own parser (see "Architectural Decisions").
- **Conservative fallback answer** (`backend/app/tutor/conservative.py`):
  `build_conservative_answer` — built directly from tool-call data, no LLM
  narration at all, so it is grounded by construction and can never fail
  its own citation check. This is the path `LLM_PROVIDER=none` (this
  project's permanent default) actually exercises end to end, exactly like
  every other agent's own "what really runs in this environment" fallback.
- **G4 Tutor graph** (`backend/app/orchestration/graphs.py::build_tutor_graph`,
  replacing the Phase 1 placeholder): a real, bounded LangGraph —
  `classify_intent -> plan_tools -> [refuse | call_tools -> compose_answer
  -> verify_citations -> [regenerate once, attempt <= 2] ->
  finalize_verified | conservative_answer]`. Unlike G3, this graph has no
  interleaved DB *writes* forcing plain async orchestration instead (every
  step here is a read), so it is a real `StateGraph`, same as G1/G2.
- **Report Builder** (`backend/app/tutor/report_builder.py`): the phase
  brief's explicit requirement — `build_progress_report()` is a **pure
  function** (no DB/gateway import) that deterministically buckets the Gap
  Engine's own already-computed `SkillGapEntry.status` values: `MET` ->
  `acquired` (reusing the Gap Engine's own `strengths[]` output directly,
  never re-deriving mastery/evidence), `WEAK` -> `in_progress`, everything
  else (`MISSING`/`BLOCKED`/`UNVERIFIED`) -> `remaining_gaps`; open
  `StruggleSignal`s and active `LearnerMisconception`s -> `struggle_areas`;
  `PlanItem.status` `done`/`planned` -> `completed_work`/`next_steps`
  (sorted by `day_slot`, capped at `PROGRESS_REPORT_NEXT_STEPS_LIMIT`). An
  async `compute_progress_report()` wrapper fetches the real rows and calls
  straight through — it never recalculates a bucket itself. The LLM only
  narrates the finished report afterward (`app/tutor/service.py::narrate_progress`,
  reusing the Tutor Agent rather than a separate narration agent, matching
  design's own "no separate Summary Agent" decision) — it never computes
  any of `ProgressReport`'s statistics (the phase brief's explicit
  requirement).
- **Orchestration glue** (`backend/app/tutor/service.py`,
  `backend/app/tutor/context.py`): `build_tutor_context()` assembles the
  per-turn `TutorContext` (learner's role, a precomputed `GapAnalysisResult`,
  every repo/service a tool might need) the same way `app/planning/service.py`
  builds its own per-run services; `run_chat()` compiles and runs the G4
  graph; `narrate_progress()` collapses the graph's
  `compose_answer -> verify_citations -> [retry once] -> conservative`
  ladder down to its essentials for the one-tool-result progress-narration
  case.
- **Schemas**: `ProgressReport` (`backend/app/schemas/common.py`) got its
  real design §25.2 field list this phase (previously
  `{learner_id, data: dict}`), plus three new supporting sub-models
  (`ProgressSkillEntry`, `StruggleAreaEntry`, `ProgressActivityEntry`).
  `backend/app/schemas/tutor.py` (new, response/request-only, same latitude
  `schemas/gap.py`/`schemas/planning.py`/`schemas/assessment.py` already
  used): `ChatRequest`, `ChatResponse`, `DecisionRecordOut`.
- **API routes** (`backend/app/api/v1/tutor.py`, design §27):
  `POST /api/learners/me/chat` (plain JSON request/response, **not** design
  §27's SSE stream — see "Architectural Decisions" for why),
  `GET /api/learners/me/progress` (`?period=`), `GET /api/decisions/{id}`.
  `learner_id` always resolved from the session
  (`get_current_learner_id`), matching every other learner-scoped route.
- **Addition**: `ReflectionRepository.get_decision_record(learner_id,
  decision_id)` — a learner-scoped `DecisionRecord` lookup, backing both
  the `get_decision` tool and `GET /api/decisions/{id}`.
- **No new database tables.** The Tutor reads exclusively from tables every
  earlier phase already owns (`LearnerSkillState`/`Evidence`/`WeeklyPlan`/
  `PlanRevision`/`PlanItem`/`StruggleSignal`/`LearnerMisconception`/
  `DecisionRecord`) — read-only by construction, so there was nothing new
  to persist.
- **New `core/thresholds.py` constants**: `TUTOR_MAX_TOOL_STEPS` (4, design
  P6's "tutor tool steps ≤ 4"), `TUTOR_MAX_COMPOSE_ATTEMPTS` (2 — the first
  draft plus exactly one citation-failure regeneration),
  `TUTOR_SEARCH_RESOURCES_TOP_K`, `PROGRESS_REPORT_NEXT_STEPS_LIMIT`.
- **Tests**: 49 new — `tests/test_provenance_citations.py` (5, pure),
  `tests/test_report_builder.py` (7, pure, hand-built `GapAnalysisResult`
  fixtures mirroring `test_gap_engine.py`'s style), `tests/test_tutor_tools.py`
  (11, against the real curated dataset via `catalog_session`: every tool's
  `citable_ids` checked to be a subset of real, resolvable IDs, learner
  scoping on `get_decision`), `tests/test_tutor_intent.py` (10, pure
  `plan_tools` mapping plus real-catalog skill-mention matching),
  `tests/test_tutor_agent.py` (5, mirroring `test_reflection_agent.py`'s
  `ScriptedLLMGateway` pattern), `tests/test_tutor_service.py` (4, the real,
  always-live conservative-answer path end to end against the real
  catalog — LLM_PROVIDER=none means this is what actually runs, not a
  mocked LLM response), `tests/test_tutor_api.py` (7, full HTTP-layer flow
  via the existing `app_client` fixture: chat/progress/decisions,
  intake-required 404s, out-of-scope refusal). **455 tests total, all
  passing** (406 from Phase 1-9, 49 new).

**Phase 11 — Frontend** (design: `docs/FRONTEND_DESIGN_SYSTEM.md`; contracts:
ARCHITECTURE_CONTRACTS.md §20 backend read-model/trace, §21 frontend):

- **Frontend stack:** Next.js 16.3 App Router, React 19.2, Tailwind v4, shadcn/ui
  (base-nova on Base UI; `components.json`), Motion 13 (`motion/react`), lucide-react,
  Atkinson Hyperlegible Next + Barlow Semi Condensed (next/font). Light theme only.
- **Design tools:** UI/UX Pro Max installed to `.claude/skills/ui-ux-pro-max` (its generic
  "education" palette/fonts were rejected as off-brief; UX/accessibility rules used); Impeccable
  plugin (direction round: "The Checked Set", `PRODUCT.md`, `.impeccable/surfaces/`);
  frontend-design plugin; Playwright 1.63 + Chromium + `@axe-core/playwright`.
- **MCP:** 21st MCP added at *local* scope (`claude mcp add --transport http 21st ...`, key in
  `~/.claude.json`, not in the repo); `claude mcp list` reports Connected; its tools only load into
  a session after restart, so no 21st component was used this session.
- **Installed dependencies (frontend):** motion, @base-ui/react, class-variance-authority,
  lucide-react, tw-animate-css, shadcn, clsx, tailwind-merge, @playwright/test,
  @axe-core/playwright. (shadcn's stray `cn` package was removed.)
- **Screens:** `/` landing (server component), `/start` onboarding (goal, upload, claim review,
  first plan), `/dashboard` overview, `/dashboard/{evidence,skills,gaps,plan,practice,progress,
  tutor,trace}`. Skill drawer and Why drawer are shared. Centrepiece: `AdaptiveMoment` on the plan.
- **State/data:** `lib/api-client.ts` (typed), `lib/types.ts`, `lib/query.ts` (tiny cache),
  `lib/hooks.ts`, `lib/trace-store.ts` (SSE), `lib/derived.ts`, `lib/format.ts`.
- **Backend additions:** `api/v1/views.py` + `schemas/views.py` (roles, catalog skills/resources,
  profile, evidence, skill detail, revision list/detail, `PATCH` plan-item status);
  `decision_id`/`reflection_id` on `ReflectionOut`; `sse/trace.py` replay buffer + `emit()` +
  `TraceRunMiddleware` (`X-Run-Id`); emit points in profiling, planning, assessment, reflection;
  fixed `/progress` 500 when a misconception exists. Backend tests: 466 pass.
- **Verification:** `npm run build`, `npx eslint .`, `npx tsc --noEmit` clean;
  `npx playwright test` (needs live API + `npm run start`): 56 breakpoint/overflow/console/axe/keyboard
  checks pass; `e2e/journey.spec.ts` (fresh DB) drives intake to reflection to revert on the real API.
- **Demo mode:** `NEXT_PUBLIC_DEMO_MODE=true` (frontend/.env.local, git-ignored). Adds "Fill in for
  Asha", "Use the demo resume", and "answer with a common misconception" (uses
  `public/demo/struggle-answers.json`, derived from the item bank). All go through real endpoints.

#### Phase 12 — Integration, Evaluation and Demo Hardening

- **Observability** (`app/observability/`, `app/sse/trace.py`, `app/main.py`): `TraceRunMiddleware`
  opens a `RunContext` per `/api` request (client `X-Run-Id` or a UUID, echoed back as `X-Run-Id`),
  persists `AgentRun` + `AgentStep` (migration `0007_observability`) with run/step/learner ids,
  actor, `input_ref`/`output_ref`, `decision_id`, duration, tokens/cost, status; the gateway, the
  retrieval service, the planning graph and the agents report LLM calls / retries / planner loops /
  retrieval time. `emit(..., publish=False)` keeps audit-only steps out of the learner-facing SSE
  panel. `GET /api/runs/{id}` (owner only), `/api/learners/me/runs`, `/api/metrics`.
  ARCHITECTURE_CONTRACTS.md section 22.
- **LLM Gateway** (`app/gateway/llm_gateway.py`, `providers.py`): never raises; replay, live,
  recorded, then degrade; retries <= 2 with backoff; durable `llm_replay_entries` (`DbReplayCache`;
  process-local on SQLite because a second session on the shared in-memory connection would roll back
  the request's writes); an `anthropic` adapter over `httpx`; token/cost accounting. The embedding,
  VLM and web-fallback gateways no longer raise for a configured provider (they always degrade).
- **DEMO_MODE** (`app/demo/`, `api/v1/demo.py`, `scripts/seed_demo.py`): `POST /api/demo/seed`
  (fixed learner `demo-learner-asha`; intake, resume, confirm, seeded evidence state, plan, all through
  the real services), `POST /api/demo/scripted-attempt` (keys resolved server-side),
  `GET /api/demo/preflight`, `erase_learner_data`. `app/profiling/intake.py` was extracted from the
  learners route so the route and the seeder share one code path. Dataset fixes at the source:
  scenario answers now name real distractors (the validator enforces it), persona coursework chain
  added, expected operators corrected.
- **Journey driver** (`app/demo/journey.py`, `scripts/run_journey.py`): the complete journey over
  HTTP; the integration test, the smoke test/benchmark and the rehearsal are the same code.
- **Deployment** (`docker-compose.yml`, `app/catalog/bootstrap.py`, `frontend/Dockerfile`): catalog
  seeded on first start (only when empty), `./data` mounted, `DATASET_DIR`, API healthcheck,
  `web` waits for a healthy API, document volume, `NEXT_PUBLIC_*` as build args.
- **Bug fixes found by the hardening:** see FINAL_IMPLEMENTATION_STATUS.md section 3 (a provider other
  than `none` crashed the app; compose left the catalog empty; demo scenario drifted from the bank;
  Tutor `search_resources` omitted `met_skill_ids`; 500s lacked CORS headers; catalog alias gaps).
- **Tests** (466 to 572): `tests/integration/` (full journey, live + seeded), `tests/evaluation/`
  (evidence, normalization, gap oracle, prerequisites, retrieval + ablation, plan personas, struggle
  simulation, reflection, adaptation events, citations, performance; writes
  `backend/reports/evaluation_metrics.{json,md}`), `tests/security/`, `test_observability.py`,
  `test_llm_gateway.py`, `test_demo_mode.py`, `test_tutor_search_resources.py`.

### Files Created / Modified

**Backend** (`backend/`):
- `pyproject.toml`, `alembic.ini`, `pytest.ini`, `Dockerfile`, `.dockerignore`
- `app/__init__.py`, `app/main.py` (extended, Phase 4: startup Skill Graph
  cache on `app.state`), `app/config.py`, `app/logging_config.py`
- `app/core/__init__.py`, `app/core/errors.py`
- `app/schemas/__init__.py`, `app/schemas/envelope.py`,
  `app/schemas/common.py` (extended, Phase 4: real `SkillGap`/
  `LearningObjective` field lists; extended, Phase 6: real
  `ResourceRecommendation` field list; extended, Phase 5: real
  `WeeklyPlan`/`PlanItem` field lists, new `PlanItemReason`; extended,
  Phase 8: real `AssessmentResult`/`StruggleSignal` field lists, new
  `AssessmentItemResult`; extended, Phase 9: real `ReflectionResult` field
  list), `app/schemas/gap.py` (new, Phase 4),
  `app/schemas/planning.py` (new, Phase 5: `CreatePlanRequest`),
  `app/schemas/assessment.py` (new, Phase 8; extended, Phase 9:
  `RemediationOut` replaced by `ReflectionOut`)
- `app/db/__init__.py`, `app/db/base.py`, `app/db/session.py`,
  `app/db/models.py` (extended, Phase 3 and Phase 2 — see below; extended,
  Phase 5: `WeeklyPlan`, `PlanRevision`, `PlanItem`; extended, Phase 8:
  `PracticeSession`, `Assessment`, `StruggleSignal`, `LearnerMisconception`;
  extended, Phase 9: `ReflectionRecord`, `DecisionRecord`)
- `app/db/migrations/env.py`, `app/db/migrations/script.py.mako`,
  `app/db/migrations/versions/0001_foundation.py`,
  `app/db/migrations/versions/0002_skill_graph_catalog.py` (Phase 3),
  `app/db/migrations/versions/0003_learner_profiling.py` (Phase 2),
  `app/db/migrations/versions/0004_planner.py` (Phase 5),
  `app/db/migrations/versions/0005_assessment.py` (Phase 8),
  `app/db/migrations/versions/0006_reflection.py` (new, Phase 9)
- `app/gateway/__init__.py`, `app/gateway/llm_gateway.py`,
  `app/gateway/embedding_gateway.py` (Phase 3),
  `app/gateway/vlm_gateway.py` (new, Phase 2),
  `app/gateway/web_fallback_gateway.py` (new, Phase 6)
- `app/orchestration/__init__.py`, `app/orchestration/state.py`,
  `app/orchestration/graphs.py` (extended, Phase 2: real
  `build_onboarding_graph`; extended, Phase 5: real `build_planning_graph`,
  replacing the placeholder; extended, Phase 9: `build_evidence_response_graph`'s
  docstring rewritten to explain it stays a placeholder by design)
- `app/agents/__init__.py`, `app/agents/base.py`,
  `app/agents/profiler.py` (extended, Phase 2: real `ProfilerAgent`),
  `app/agents/planner.py` (extended, Phase 5: real `PlannerAgent`),
  `app/agents/assessor.py` (extended, Phase 8: real `AssessorAgent`),
  `app/agents/reflection.py` (extended, Phase 9: real `ReflectionAgent`,
  mode (b) only), `app/agents/tutor.py`
- `app/services/__init__.py`
- `app/repositories/__init__.py`,
  `app/repositories/user_repository.py` (extended, Phase 2: `get_or_create`),
  `app/repositories/catalog_repository.py` (Phase 3; extended, Phase 6:
  `get_resources_targeting_skill`, `update_link_statuses`; extended, Phase 5:
  `get_resources_by_ids`, `get_practice_items_for_skill`; extended, Phase 8:
  `get_practice_item`, `get_practice_items_by_ids`, `create_practice_item`,
  `get_misconception`, `get_misconceptions_for_skill`),
  `app/repositories/profiling_repository.py` (new, Phase 2),
  `app/repositories/planning_repository.py` (new, Phase 5; extended, Phase
  9: `mark_reverted`),
  `app/repositories/assessment_repository.py` (new, Phase 8; extended,
  Phase 9: `all_assessment_item_ids_for_learner`),
  `app/repositories/reflection_repository.py` (new, Phase 9)
- `app/graph/__init__.py`, `app/graph/loader.py`,
  `app/graph/queries.py` (extended, Phase 4: `hard_prerequisite_out_edges`,
  `part_of_children`), `app/graph/validation.py` (Phase 3)
- `app/catalog/__init__.py`, `app/catalog/ingest.py` (Phase 3)
- `app/gap/__init__.py`, `app/gap/engine.py` (new package, Phase 4;
  extended, Phase 8: public `current_level_for`/`mastery_estimate_for`
  wrappers)
- `app/retrieval/__init__.py`, `app/retrieval/ranker.py`,
  `app/retrieval/service.py`, `app/retrieval/link_validator.py` (new
  package, Phase 6)
- `app/planning/__init__.py`, `app/planning/candidates.py`,
  `app/planning/prompting.py`, `app/planning/validator.py`,
  `app/planning/fallback.py`, `app/planning/service.py` (new package,
  Phase 5)
- `app/assessment/__init__.py`, `app/assessment/mastery.py`,
  `app/assessment/struggle.py`, `app/assessment/grading.py`,
  `app/assessment/prompting.py`, `app/assessment/item_bank.py`,
  `app/assessment/resolution.py` (new package, Phase 8; unchanged, Phase 9
  — now Reflection's last-resort fallback, see `app/reflection/service.py`),
  `app/assessment/service.py` (extended, Phase 9: routes through
  `app/reflection/service.py::run_reflection` instead of calling
  `resolution.start_remediation` directly; `SubmitOutcome.remediation`
  renamed `.reflection`)
- `app/reflection/__init__.py`, `app/reflection/operators.py`,
  `app/reflection/evidence.py`, `app/reflection/deterministic.py`,
  `app/reflection/draft.py`, `app/reflection/prompting.py`,
  `app/reflection/validator.py`, `app/reflection/service.py` (new package,
  Phase 9)
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
  `DEFAULT_SESSION_CAP_MINUTES`; extended, Phase 5:
  `WEEKLY_BUDGET_SLACK`/`OVERLOAD_BUDGET_FACTOR`/
  `NEW_SKILL_CONCURRENCY_CAP*`/`SESSION_CHUNK_MAX_MINUTES`/
  `PROBE_ITEM_*`/`PRACTICE_ITEM_*`/`PLANNER_MAX_DRAFT_ATTEMPTS`; extended,
  Phase 8: `MASTERY_*`, `PRACTICE_SET_*`/`ASSESSOR_MAX_RETRIES`,
  `LOW_SCORE_*`/`REPEATED_MISCONCEPTION_*`/`MISSING_PREREQUISITE_*`/
  `EXCESSIVE_DIFFICULTY_*`/`DIFFICULTY_LABEL_TO_LEVEL`/`OVERLOAD_*`/
  `INSUFFICIENT_PRACTICE_MAX_N_OBS`, `STRUGGLE_REVISION_COOLDOWN_HOURS`,
  `MAX_REMEDIATION_CYCLES`; extended, Phase 9: `REFLECTION_MAX_ROUNDS`,
  `REFLECTION_REVISION_COOLDOWN_HOURS`, `REFLECTION_DEFER_DAYS`,
  `PLAN_WEEK_MAX_DAY_SLOT`)
- `app/schemas/profiling.py` (new, Phase 2)
- `app/sse/__init__.py`, `app/sse/trace.py`
- `app/api/__init__.py`, `app/api/deps.py` (extended, Phase 2:
  `get_current_learner_id`; extended, Phase 4: `get_skill_graph_service`)
- `app/api/v1/__init__.py`,
  `app/api/v1/router.py` (extended, Phase 4: registers `gap_router`;
  extended, Phase 5: registers `plans_router`; extended, Phase 8: registers
  `practice_router`),
  `app/api/v1/health.py`, `app/api/v1/runs.py`,
  `app/api/v1/learners.py` (new, Phase 2), `app/api/v1/gap.py` (new, Phase 4),
  `app/api/v1/plans.py` (new, Phase 5; extended, Phase 9: revert route),
  `app/api/v1/practice.py` (new, Phase 8; extended, Phase 9:
  `remediation` -> `reflection` response field)
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
  (all new, Phase 6);
  `tests/test_plan_validator.py`, `tests/test_fallback_planner.py`,
  `tests/test_planner_agent.py`, `tests/test_planning_integration.py`,
  `tests/test_plans_api.py` (all new, Phase 5);
  `tests/test_mastery.py`, `tests/test_struggle_classifier.py`,
  `tests/test_grading.py`, `tests/test_assessor_agent.py`,
  `tests/test_resolution.py`,
  `tests/test_assessment_integration.py` (extended, Phase 9: the
  misconception test's `.remediation` assertions updated to `.reflection`),
  `tests/test_practice_api.py` (all new, Phase 8);
  `tests/test_reflection_operators.py`, `tests/test_reflection_validator.py`,
  `tests/test_reflection_agent.py`, `tests/test_reflection_service.py` (all
  new, Phase 9);
  `app/tutor/__init__.py`, `app/tutor/context.py`, `app/tutor/tools.py`,
  `app/tutor/intent.py`, `app/tutor/draft.py`, `app/tutor/prompting.py`,
  `app/tutor/conservative.py`, `app/tutor/report_builder.py`,
  `app/tutor/service.py` (new package, Phase 10);
  `app/provenance/__init__.py`, `app/provenance/citations.py` (new package,
  Phase 10); `app/agents/tutor.py` (extended, Phase 10: real `TutorAgent`,
  replacing the placeholder); `app/orchestration/graphs.py` (extended,
  Phase 10: real `build_tutor_graph`, replacing the placeholder);
  `app/repositories/reflection_repository.py` (extended, Phase 10:
  `get_decision_record`); `app/schemas/common.py` (extended, Phase 10: real
  `ProgressReport` field list, new `ProgressSkillEntry`/`StruggleAreaEntry`/
  `ProgressActivityEntry`); `app/schemas/tutor.py` (new, Phase 10);
  `app/api/v1/tutor.py` (new, Phase 10); `app/api/v1/router.py` (extended,
  Phase 10); `app/core/thresholds.py` (extended, Phase 10:
  `TUTOR_MAX_TOOL_STEPS`/`TUTOR_MAX_COMPOSE_ATTEMPTS`/
  `TUTOR_SEARCH_RESOURCES_TOP_K`/`PROGRESS_REPORT_NEXT_STEPS_LIMIT`);
  `tests/test_provenance_citations.py`, `tests/test_report_builder.py`,
  `tests/test_tutor_tools.py`, `tests/test_tutor_intent.py`,
  `tests/test_tutor_agent.py`, `tests/test_tutor_service.py`,
  `tests/test_tutor_api.py` (all new, Phase 10)

**Phase 12** (`backend/`): `app/observability/{context,store}.py`, `app/gateway/providers.py`,
`app/demo/{service,journey}.py`, `app/catalog/bootstrap.py`, `app/profiling/intake.py`,
`app/api/v1/{observability,demo}.py`, `app/db/migrations/versions/0007_observability.py`,
`scripts/{run_journey,seed_demo}.py`; modified: `gateway/{llm,embedding,vlm,web_fallback}_gateway.py`,
`sse/trace.py`, `main.py`, `config.py`, `core/errors.py`, `db/models.py`, `api/deps.py`,
`api/v1/{learners,practice,router}.py`, `agents/*.py` (retry notes), `orchestration/graphs.py`,
`reflection/service.py`, `retrieval/service.py`, `tutor/tools.py`, `catalog/ingest.py`;
tests listed above. Root: `docker-compose.yml`, `.env.example`, `.gitignore`, `README.md`,
`frontend/Dockerfile`, `data/scripts/{build_dataset,validate_dataset}.py` + regenerated
`data/dataset/`, `docs/FINAL_IMPLEMENTATION_STATUS.md`.

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
`./storage/documents`, relative to the backend process's cwd; gitignored). **Phase 12:** `LLM_BASE_URL`, `LLM_TIMEOUT_S`, `LLM_RECORD`,
`LLM_COST_PER_1K_INPUT_USD`/`_OUTPUT_USD`, `DATASET_DIR`, `AUTO_SEED_CATALOG` (full table:
`docs/FINAL_IMPLEMENTATION_STATUS.md` section 10).

### Database Status

Postgres 16 + pgvector, running via Docker Compose, migrated with Alembic.
Five migrations: `0001_foundation` (`vector`/`pg_trgm` extensions, `users`),
`0002_skill_graph_catalog` (`skills`, `skill_edges`, `roles`,
`role_requirements`, `misconceptions`, `resources`, `resource_skills`,
`practice_items`, `graph_meta`, plus a generated `resources.search_vector`
tsvector column with a GIN index), `0003_learner_profiling`
(`learner_profiles`, `documents`, `evidence`, `learner_skill_states`,
`pending_claims`), `0004_planner` (`weekly_plans`, `plan_revisions`,
`plan_items`), and `0005_assessment` (`practice_sessions`, `assessments`,
`struggle_signals`, `learner_misconceptions`). All five verified this
session against a real Postgres 16 + pgvector container: `alembic
downgrade base` followed by `upgrade head` round-tripped every migration
cleanly in one pass (chosen over a single-step down/up specifically to
prove the whole chain, not just the newest step, still resolves cleanly);
a full intake → document-upload → confirm flow (Phase 2), a full intake →
create-plan → get-current-plan flow (Phase 5), and a full intake →
create-practice-set → submit flow with real `skill.chain_rule` items
(Phase 8, this session) were all run against the real container through
the actual FastAPI app (not just SQLite) — the intake flow is what caught
the `users` FK bug documented above under "Completed Work", the plan flow
returned a real `resource_id` from the 158-skill catalog end to end, and
the practice flow correctly triggered deterministic remediation with real
`misc.chain_rule_sum` resources once two distinct wrong-tagged items were
submitted for the same (fresh) learner.

**Phase 12 added migration `0007_observability`** (`agent_runs`, `agent_steps`, `llm_replay_entries`);
the chain is now `0001`..`0007` (the paragraph above predates Phases 9 and 12). Its SQL was compiled
for PostgreSQL offline (`alembic upgrade 0006_reflection:0007_observability --sql`); it has not been run
against a live Postgres in this session.

No other table in the conceptual schema (`LearningObjective`, `Resource`
already exists from Phase 3, `PracticeTask`, `LearningActivity`,
`ReflectionRecord`, `DecisionRecord`, `AgentRun`, `AgentStep`, ...) exists
yet — each is created by the migration the owning phase adds. **Phase 4
(Gap Engine) added no migration**: `SkillGap`/`LearningObjective` results
are computed on demand from existing tables (`learner_skill_states`,
`evidence`) plus the in-memory graph, not persisted — see
ARCHITECTURE_CONTRACTS.md §4's "Decided (Phase 4)" note and "Architectural
Decisions" below. **Phase 5 (Planner) and Phase 8 (Assessment) both
persist** (`WeeklyPlan`/`PlanRevision`/`PlanItem`;
`Assessment`/`StruggleSignal`/`LearnerMisconception`/`PracticeSession`) —
unlike gap analysis, a plan requires an LLM call (or the Fallback Planner)
to produce and an assessment is a point-in-time event, so recomputing
either on every read would be wasteful (Planner) or simply wrong
(Assessment — it is a historical record, not a derived view); design
§10.6's read/write matrix already lists both as writers.

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

**Phase 12 data changes:** `demo_scenario.json` now scripts answers that exist in the bank (1 tagged
wrong option on `backpropagation.3` + both `chain_rule` prerequisite-block items; the other backprop
items answered correctly), expected operators are `INSERT_REMEDIATION` + `ADD_PROBE`; `demo_learner_state.json`
gained ten coursework-level skills (algebra through matrices, activation functions, optimization, data
structures) so `chain_rule` is `UNVERIFIED` rather than `BLOCKED`; eight catalog aliases were added
("CI/CD", "Big-O", "Kubernetes", "AWS", "Terraform", "matrices", "machine learning", "REST API").
`validate_dataset.py` now fails if a scripted distractor does not exist in the item bank.

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

(Phase 12 added `GET /api/runs/{run_id}`, `GET /api/learners/me/runs`, `GET /api/metrics`,
`GET /api/demo/preflight`, `POST /api/demo/seed`, `POST /api/demo/scripted-attempt`; Phase 11 added the
read-model views. The count below predates both.)
Fifteen endpoints implemented: `GET /api/health`, `GET /api/runs/{run_id}/events`
(SSE), `POST /api/learners` (intake), `POST /api/learners/me/documents`
(multipart file or `github_url`), `GET /api/learners/me/claims/pending`,
`POST /api/learners/me/claims/confirm`, `GET /api/learners/me/gaps` (Phase
4 — optional `?role=` override), `POST /api/learners/me/plans` (Phase 5 —
`{week_index?, dry_run?, hours?}`), `GET /api/learners/me/plans/current`
(Phase 5), `POST /api/learners/me/practice` (Phase 8 — `{skill_id,
purpose?}`), `POST /api/practice/{set_id}/submit` (Phase 8, response field
renamed `remediation` -> `reflection` in Phase 9),
`POST /api/learners/me/plans/{plan_id}/revisions/{revision_id}/revert`
(Phase 9 — design §20.7's one-click Revert; only the plan's current
revision may be reverted), `POST /api/learners/me/chat` (new, Phase 10 —
plain JSON, not design §27's SSE stream, see ARCHITECTURE_CONTRACTS.md §19),
`GET /api/learners/me/progress` (new, Phase 10 — `?period=`),
`GET /api/decisions/{id}` (new, Phase 10 — learner-scoped `DecisionRecord`
resolution). The rest of design §27's table (target-role change, plan
override, revisions listing, dispute, demo seed) is not implemented yet.
`POST /api/plans/{id}/override` in particular is design's own surface for
`patch_existing_plan`, which Phase 5 implements as a service-layer
capability (`app/planning/service.py`) without an HTTP route of its own —
Reflection (Phase 9) does not add that route either, since it applies its
own operator pipeline directly rather than calling `patch_existing_plan`
(see ARCHITECTURE_CONTRACTS.md §18); the Tutor (Phase 10) doesn't add it
either — it never drafts an override at all this phase (see
ARCHITECTURE_CONTRACTS.md §19). `GET /api/plans/{id}/revisions` (a
plain listing) is also still unimplemented, even though Revert itself now
exists.
`SkillGraphService`/`CatalogRepository` (Phase 3) are still internal
services with no direct HTTP surface of their own beyond `/gaps`/`/plans`/
`/practice`/`/chat`/`/progress`/`/decisions`; the intake route reads
`CatalogRepository.get_role` for role validation, but nothing exposes
`/skills/{id}` or similar yet. **The Resource Retriever/Ranker (Phase 6)
still has no HTTP surface of its own** — by design (ARCHITECTURE_CONTRACTS.md
§15: design §27's table has no row for it; it's Planner-internal) — but it
is now a real, exercised dependency of both `/plans` (Phase 5) and the
Tutor's `search_resources` tool (Phase 10).

### Agent Status

**All five LLM agents are now real**: the Profiler Agent (A1,
`app/agents/profiler.py`, Phase 2), the Planner Agent (A2,
`app/agents/planner.py`, Phase 5 — draft/patch modes), the Assessor
Agent (A3, `app/agents/assessor.py`, Phase 8 — item generation + blind-solver
validation), the Reflection Agent (A4, `app/agents/reflection.py`, Phase
9 — mode (b) evidence reflection only; mode (a) plan-critique is not
implemented, see "Known Issues" below), and the Tutor Agent (A5,
`app/agents/tutor.py`, Phase 10 — `compose_answer` only; `classify_intent`/
`plan_tools` are deliberately rule-based, not the agent's own job, see
ARCHITECTURE_CONTRACTS.md §19). Three LangGraph business graphs exist for
real: G1 Onboarding (`build_onboarding_graph`), G2 Planning
(`build_planning_graph`, Phase 5 — `build_objectives ->
retrieve_candidates -> plan_draft -> validate_plan -> [retry <= 2] ->
fallback_plan`, no `critique` node since Reflection mode (a) is out of
scope), and **G4 Tutor** (`build_tutor_graph`, Phase 10 — `classify_intent
-> plan_tools -> [refuse | call_tools -> compose_answer -> verify_citations
-> [regenerate once] -> finalize | conservative_answer]`); **G3
Evidence-Response is implemented only as plain async orchestration**, split
across `app/assessment/service.py`'s
`submit_practice_set` (`record_evidence -> grade -> update_mastery ->
detect_struggle -> route`) and `app/reflection/service.py`'s
`run_reflection` (`reflect -> validate_reflection -> [retry <= 2] ->
deterministic patch -> commit`), not as an explicit LangGraph `StateGraph`
the way G1/G2/G4 are — each step needs a DB write the next step's read
depends on (a materialized probe session before `ADD_PROBE` can reference
real item IDs; mastery written before struggle classification reads it),
and no Postgres-backed LangGraph checkpointer exists to pause a graph
mid-run for that (see "Known Issues"). G4 has no such interleaved-write
problem — every one of its steps is a read — which is exactly why it *is* a
real `StateGraph` unlike G3. No agent other than the Profiler, Planner,
Assessor, Reflection, and Tutor has tool access; none has any
*side-effect* tool exposed to it — the Reflection Agent chooses among a
pre-resolved candidate ID set (root-cause skill, remediation resources,
probe items) and never calls `commit_*`/writes anything itself, per
ARCHITECTURE_CONTRACTS.md §13; the actual `PlanRevision`/`ReflectionRecord`/
`DecisionRecord` writes happen in `app/reflection/service.py` after the
deterministic Reflection Validator approves. The Tutor's nine tools are
*all* reads (`app/tutor/tools.py`) — no `commit_*` tool is in its inventory
at all, and it cannot even draft a plan override this phase (see
ARCHITECTURE_CONTRACTS.md §19). The Gap Engine (Phase 4), the
Resource Retriever/Ranker (Phase 6), the Plan Validator and Fallback Planner
(Phase 5), the Mastery Updater, Struggle Classifier, and misconception
resolution state machine (Phase 8), the Reflection Validator +
deterministic root-cause/operator policy (Phase 9), and the Report Builder
+ citation verifier (Phase 10) are **not** LLM agents —
all eleven are deterministic services ARCHITECTURE_CONTRACTS.md §2 explicitly
excludes from that list; no LLM call exists anywhere in `app/gap/`,
`app/retrieval/`,
`app/planning/validator.py`, `app/planning/fallback.py`,
`app/assessment/mastery.py`, `app/assessment/struggle.py`,
`app/assessment/resolution.py`, `app/reflection/validator.py`,
`app/reflection/operators.py`, `app/reflection/deterministic.py`,
`app/tutor/report_builder.py`, `app/tutor/intent.py`,
`app/tutor/conservative.py`, or `app/provenance/citations.py`.

### Tests Status

Backend: **601 tests, all passing after Phase 12b** (466 before it; the per-phase breakdown
below stops at 455). Phase 12's tiers: `tests/integration`, `tests/evaluation` (writes
`backend/reports/`), `tests/security`. Historic text: **455 tests** (`backend/tests/`) — run with
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
path — see the Phase 6 "Tests" bullet under "Completed Work" above) plus
Phase 5's 42 (Plan Validator rules, the Fallback Planner's "always valid"
contract re-verified against `validate_plan` directly, the Planner Agent's
retry/invented-ID-rejection/patch-mode behavior, a real-catalog
Gap-Engine-through-Fallback-Planner run, `create_plan`/`patch_existing_plan`
against a real session, and the `/plans` API routes — see the Phase 5
"Tests" bullet under "Completed Work" above) plus Phase 8's 89 (the Mastery
Updater's Beta-count formula, all six Struggle Classifier classes
individually, MCQ/short-answer grading, the Assessor Agent's generation +
blind-solver-validation + invented-tag-rejection behavior, the
misconception resolution state machine, a real-catalog confirmed-
misconception-to-real-remediation-resources round trip, and the
`/practice` API routes — see the Phase 8 "Tests" bullet under "Completed
Work" above) plus Phase 9's 31 (every closed-set operator individually, the
Reflection Validator's five checks, the Reflection Agent's degrade/valid-
draft/invented-ID-retry behavior, and the real-catalog chain_rule ->
backpropagation wow scenario end to end — see the Phase 9 "Tests" bullet
under "Completed Work" above) plus Phase 10's 49 (citation verification,
the Report Builder's deterministic bucketing, every Tutor tool's
citable-ID-is-always-real property against the real curated dataset,
rule-based intent classification, the Tutor Agent's degrade/valid-draft/
malformed-JSON-retry behavior, the real always-live conservative-answer
path end to end, and the full `/chat`/`/progress`/`/decisions` HTTP-layer
flow — see the Phase 10 "Tests" bullet under "Completed Work" above). All run against SQLite (`tests/conftest.py`'s existing
dialect-portability convention); the Postgres-only catalog paths
(`CatalogRepository.search_resources_by_text`/`search_resources_by_vector`,
the generated `search_vector` column), the full learner-profiling flow, the
full intake → create-plan → get-current-plan flow (Phase 5), and (Phase 8,
this session) the full intake → create-practice-set → submit ->
deterministic-remediation flow were all verified manually against a real
Postgres 16 + pgvector container instead (see "Database Status" above)
rather than added to the automated suite, since the project has no
Postgres-backed CI/test tier yet.

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
- **(Phase 9) `skill.chain_rule` has no curated `purpose="resolution-check"`
  practice items** (only `skill.backpropagation.6` does) — a data gap, not a
  Reflection bug. `app/assessment/item_bank.py::assemble_practice_set`'s
  `resolution-check` branch has no generation fallback (by design, same
  posture as the rest of that module), so a resolution-check probe scheduled
  on `skill.chain_rule` specifically carries zero `practice_item_ids` in
  this environment; `tests/test_reflection_service.py`'s wow-scenario test
  documents this rather than asserting around it. Fix by either curating a
  `resolution-check` item for `skill.chain_rule` or having `ADD_PROBE` fall
  back to `purpose="prereq-block"`/`"practice"` items when none exist.
- **(Phase 9) `DEFER` with no matching items is a no-op, not an error** —
  deliberate (a struggling skill may not yet have a scheduled item this
  week; "push out whatever is there" is vacuously satisfied by nothing being
  there), but means a caller cannot distinguish "successfully deferred
  zero items" from "the skill_id was a typo" from the return value alone;
  `ApplyResult.diff["deferred"]` being empty is the only signal.
- **(Phase 9) design §20.8's "deferred items reinstated" on resolution is
  not implemented** — `resolution.record_probe_result` still only
  transitions `LearnerMisconception.status`; nothing tracks which plan
  item(s) a given reflection deferred so a later `resolved` status could
  pull them back to an earlier `day_slot`. Would need either a new column
  linking a deferred `PlanItem`/objective back to its `ReflectionRecord`, or
  a lookup through `PlanRevision.diff`'s `"deferred"` list.
- **(Phase 10) `POST /api/learners/me/chat` is not the SSE stream design §27
  describes** — it returns the complete, citation-verified answer as one
  JSON body. `app/sse/trace.py`'s `TraceBus` already exists for a later
  phase to wire token-by-token streaming onto once a UI needs it.
- **(Phase 10) no chat-turn persistence.** Design §21's "session memory"
  (chat window, last N turns) is not stored anywhere — each `/chat` call is
  independently grounded in its own fresh tool calls (design §23.3's "not
  cached across learners" is honored; multi-turn conversational memory
  across separate HTTP requests is not). A real chat UI would need a
  `ChatTurn`-shaped table (or per-`run_id` state) to show history back to
  the user; nothing in this phase reads or writes one.
- **(Phase 10) the Tutor never drafts a plan override.** Design §23.3's
  "it can offer an override... which becomes an explicit API call after the
  user confirms" is not implemented at all this phase — not even the
  drafting half. `POST /api/plans/{id}/override` remains unimplemented (see
  "API Status" above).
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
- **(Phase 5, revised)** V8 (struggle follow-up) is effectively a no-op —
  a real per-learner `struggle_signals` table now exists (Phase 8), but the
  Plan Validator's V8 check was never wired to read it; V9's
  `overload_active` flag (`effective_budget_minutes`/`effective_new_skill_cap`,
  `app/planning/validator.py`) likewise has no real trigger yet. Both are
  mechanism-now-source-later, same pattern Phase 6 already used for
  `learner_history` — now that the source exists (Phase 8), wiring it into
  a `create_plan`/`patch_existing_plan` call is Reflection's job (design
  §20's re-planning trigger), still out of scope.
- **(Phase 5)** `LearningObjective.est_minutes_low/high` is **still**
  `None` on `/gaps` responses, even though the Planner now has both a
  `LearningObjective` and its candidate resources in scope together
  (`app/planning/candidates.py`'s `ObjectiveCandidateSet.resources` carries
  `duration_min`) — nothing writes that back onto the Gap Engine's output.
  Not a blocker (the Planner itself doesn't consume this field), but the
  natural small follow-up the Phase 4/6 "Known Issues" notes anticipated.
- **(Phase 5)** No API route exposes `patch_existing_plan`
  (`app/planning/service.py`) — design §27's patch/override surface
  (`POST /api/plans/{id}/override`) is Reflection's (Phase 8), since
  deciding *when* a patch is warranted is that phase's job. Tested directly
  at the service layer (`tests/test_planning_integration.py`) until then.
- **(Phase 5)** `PlanItem.status` is always written as `"planned"` — no
  `POST /api/plan-items/{id}/complete` endpoint or `LearningActivity` table
  exists yet (this project's Phase 8 did not add one either — see below)
  to ever transition it to `"done"`/`"skipped"`.
- **(Phase 8)** No `LearningActivity` table exists yet, so
  `cognitive_overload`'s `planned_vs_actual_ratio`/`completion_rate`
  signals are still caller-supplied parameters
  (`submit_practice_set`/`SubmitPracticeRequest`), never queried from live
  data — same "mechanism now, real source later" pattern already used
  elsewhere (Phase 6's `learner_history`, Phase 5's `overload_active`).
  `self_reported_overload`/`retries_trend_rising`/`new_skills_active` are
  real request fields a client *can* populate today; the other two never
  will be until that table exists.
- **(Phase 8)** `missing_prerequisite`'s "direct probe" evidence
  (`StruggleContext.prerequisite_probe_scores`) is never actually populated
  by `app/assessment/service.py` — only the "direct prereq-block items in
  the same submission" and "attribution via a misconception's ROOTED_IN
  skill" paths are wired to real data. A learner's *separate*, more recent
  assessment on the prerequisite skill could in principle supply this (the
  data exists in the `assessments` table), but nothing queries it yet — the
  classifier rule and its test coverage are both complete; only this one
  real-data source is still unwired.
- **(Phase 8)** G3 Evidence-Response is plain async orchestration
  (`app/assessment/service.py`'s `submit_practice_set`), not an explicit
  LangGraph `StateGraph` the way G1/G2 are — see "Agent Status" above for
  the reasoning. No `RunState`/trace events are emitted for a practice
  submission the way G1/G2 runs emit them; `POST /api/practice/{set_id}/submit`
  is a bare deterministic-plus-two-LLM-calls flow, more like `GET /gaps`
  (Phase 4, no orchestrator column in design §27's table) than a full
  graph run. Revisit if Reflection (design's own Phase 8) needs `route` to
  branch into more paths than "one deterministic remediation trigger."
- **(Phase 8)** `CatalogRepository.replace_all()` (Phase 3) will now fail
  with a foreign-key violation if re-run against a database that already
  has real learner-scoped rows referencing catalog data (`plan_items`,
  `evidence`, `assessments`, `struggle_signals`, `learner_misconceptions`
  all FK-reference `skills`/`resources`/`misconceptions`) — surfaced this
  session when re-seeding a dev Postgres container that already had Phase
  5/8 verification data in it. Worked around by resetting the schema
  (`alembic downgrade base` + `upgrade head`) rather than changing
  `replace_all`'s delete-then-insert shape, since that shape is itself a
  Phase 3 design decision (design §11.5: catalog is versioned and reloaded
  whole) predating any learner-scoped FK — deciding how re-ingestion should
  behave against live learner data (cascade? block with a clear error?
  something else?) is a real design question for whichever phase first
  needs to re-seed a catalog with real learners already on it, not
  something to guess at here.
- **(Phase 8)** A curated-data quirk, not a code bug: several
  `skill.chain_rule` items in `data/dataset/assessment_items.json` have
  their *correct* option also carrying a `misconception_id` tag (an
  authoring artifact — see ARCHITECTURE_CONTRACTS.md §17 and the
  "Completed Work" bullet above). `grade_mcq` already nulls any tag on a
  correct answer regardless, so this has no behavioral effect; still worth
  folding into Phase 3's still-outstanding human review pass.

- **(Phase 12, top limitation) Plans under-fill large budgets.** Retrieval's hard `duration <= session
  cap` filter removes course-length resources and nothing splits a long resource into segments, so only
  56% of role skills have an eligible lesson at the 45-minute default and a 20 h/week learner is
  scheduled ~45 minutes (utilization 38/15/8/4% at 2/5/10/20 h). Plans are valid, never over budget,
  and often thin. Fix = segment splitting in the Planner + a duplicate-rule exemption for segments of
  one resource (design V6's intent). Measured by `tests/evaluation/test_eval_gap_plan_retrieval.py`
  and `test_eval_plan_validity.py`.
- **(Phase 12) Unverified against live systems:** the Anthropic adapter, record/replay and the agents'
  LLM paths have only run with mocked HTTP / fakes; migration `0007` and the Phase 12 Postgres paths
  were checked via offline SQL and FK-enforced SQLite, not a live Postgres; `docker compose up
  --build` was not verified end to end (Docker Desktop's engine wedged mid-session). The Playwright
  suite was not re-run (the frontend is unchanged except its Dockerfile).
- **(Phase 12) Span offsets index the PII-scrubbed text** (documented contract of `scrub_pii`), not the
  stored raw file; identical when a document has no contact PII.
- **(Phase 12) Injection handling is conservative:** claims within `INJECTION_WINDOW_CHARS` (80) of a
  flagged phrase are dropped and counted (`dropped_injection`), so legitimate skills next to an injected
  sentence are lost, and ordinary phrases like "act as a liaison" can trigger it.
- **(Phase 12) `DEFER` never fires for the seeded persona** (backpropagation is BLOCKED and never
  scheduled) and `skill.chain_rule` has no `resolution-check` item; the scenario's expected operators are
  `INSERT_REMEDIATION` + `ADD_PROBE` (`DEFER` optional).
- **(Phase 12) `POST /api/demo/seed` is single-tenant** (fixed learner id; erases whatever holds it).
  `/api/metrics` is unauthenticated (aggregates only). The session cookie is an unsigned user id and
  `SESSION_SECRET` is unused. The SSE trace bus is in-process (one API worker).
- **(Resolved, Phase 12)** the in-process-only replay cache (now `llm_replay_entries`); Phase 11's
  "500s carry no CORS headers"; the `HTTP_422_UNPROCESSABLE_ENTITY` deprecation warning; `docker compose`
  starting with an empty catalog; the Tutor's `search_resources` ignoring met prerequisites.

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
- **(Phase 5)** G2 Planning's graph itself does not persist anything —
  `build_planning_graph` ends with a finalized in-memory result
  (`state["data"]["final_items"]`, etc.), and the actual `WeeklyPlan`/
  `PlanRevision`/`PlanItem` write happens in `app/planning/service.py`,
  outside the graph. Same reasoning Phase 2 used for `PendingClaim`: no
  Postgres-backed LangGraph checkpointer exists to hold in-flight state
  across a node that also needs a live DB session, so the DB write is glue
  code around a graph invocation rather than a graph node itself.
- **(Phase 5)** The Planner Agent does not own a deterministic fallback the
  way the Profiler Agent does. `PlannerAgent.run()` returns `degraded=True`
  with an empty item list on gateway unavailability or exhausted retries;
  the **G2 graph**'s `fallback_plan` node, not the agent, is what actually
  produces a plan in that case. Reason: design §9.4's node table lists
  `plan_draft` and `fallback_plan` as separate nodes (unlike G1's
  `extract_claims`, where the Profiler's own fallback extractor *is* the
  node's entire failure path) — matching the design table's shape took
  priority over reusing the Profiler's embedded-fallback pattern.
- **(Phase 5)** Candidate-ID validation happens twice, deliberately: once
  in `app/planning/prompting.py`'s `parse_planner_response` (rejects an
  invented ID as a parse error, triggering the same retry-then-degrade path
  as malformed JSON) and again in `app/planning/validator.py`'s V2
  (referential integrity, over *any* drafted plan including the Fallback
  Planner's own output). The first catches an LLM's bad output as early as
  possible and feeds back a precise error; the second is what actually
  gates a commit — neither is redundant with the other, since the Fallback
  Planner's output never goes through the parser at all.
- **(Phase 5)** `effective_budget_minutes`/`effective_new_skill_cap`
  (`app/planning/validator.py`) are free functions, not baked into
  `validate_plan`'s signature, so a caller computes the *effective* budget/
  cap once (folding in `overload_active`) and passes plain numbers into
  both the Planner Agent's prompt and the validator — keeps the "what's the
  budget for this run" computation in one place rather than duplicating
  the `* 0.9` / `* 0.8` arithmetic at each call site.
- **(Phase 8)** The Mastery Updater's tier-upgrade rule deliberately
  differs from `EvidenceCommitService`'s (Phase 2) — see
  ARCHITECTURE_CONTRACTS.md §17 for the full reasoning (accumulate vs.
  reseed). This is a considered inconsistency, not an oversight: E0-E2 are
  one-shot categorical priors representing "how strong is this *kind* of
  evidence", while E3 assessed items are individually meaningful
  observations meant to accumulate, per design §10.4's explicit
  `α += w`/`β += w` formula.
- **(Phase 8)** Misconception resolution
  (`app/assessment/resolution.py`) applies `INSERT_REMEDIATION`/
  `ADD_PROBE` directly via `PlanningRepository`, not through the Planner
  Agent's patch mode (`app/planning/service.py`'s `patch_existing_plan`,
  built in Phase 5 specifically "for Reflection to call later"). Reason:
  both operators are already fully deterministic once the trigger has
  fired (a real `REMEDIATED_BY` lookup plus a plan-revision insert), so
  routing them through an LLM-capable agent would add a gateway call (and
  its retry/degrade machinery) for a decision that isn't actually being
  made by an LLM here — the *trigger* (a confirmed misconception) is
  itself already deterministic, unlike Reflection's full root-cause
  synthesis, which genuinely needs the Planner Agent's patch mode once it
  exists.
- **(Phase 8)** `AssessorAgent`'s blind-solver validation step fails an
  item **closed** on any ambiguity — a degraded gateway, an unparsable
  response, or a wrong pick are all treated identically (the item is
  dropped, not retried, not partially trusted). Unlike the generation
  step's own retry loop (schema/tag errors are worth retrying — the model
  might just need the error message), a *validation* failure has nothing
  useful to retry against: either the item is actually solvable and the
  small model got it right (kept) or it isn't/didn't (dropped) — there is
  no corrective feedback to give a validator the way there is a generator.
- **(Phase 8)** `submit_practice_set` builds a fresh `hard_prerequisite_status`/
  `gap_statuses` view by re-running `analyze_gaps` inline, the same way
  `app/planning/service.py` and `app/api/v1/gap.py` already do, rather than
  reading a cached/stored gap report — consistent with Phase 4's "derived
  view, not stored, recomputed on demand" decision for gap analysis itself
  (ARCHITECTURE_CONTRACTS.md §4); no new caching mechanism was introduced
  for this phase's read of it.

### Contract Changes

**Phase 12:** `docs/ARCHITECTURE_CONTRACTS.md` section 14 (record/replay now implemented) and a new
section 22 (gateway resolution order and never-raises rule, run/step persistence and `X-Run-Id`, read APIs,
DEMO_MODE contract, catalog bootstrap, CORS on 500s, test tiers). Additive: `LLMResponse` gained
`tokens_in/out`, `model`, `latency_ms`, `error`; `ReplayCache.put` gained an optional `meta`; three tables;
`app/profiling/intake.py` extracted from the learners route (no behavior change).

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

`docs/ARCHITECTURE_CONTRACTS.md` §2, §6, §9, §10, and a new §16 added this
phase (Phase 5, Planner):
- §2: pointed to `backend/app/agents/planner.py` as the Planner Agent
  implementation, and `backend/app/planning/validator.py`/`fallback.py` as
  the Plan Validator/Fallback Planner implementations.
- §6: noted `WeeklyPlan`/`PlanItem` now have real field lists.
- §9: recorded the addition of `WeeklyPlan`/`PlanRevision`/`PlanItem`
  (migration `0004_planner`) to design §28's conceptual table list, and the
  one field-shape addition (`PlanItem.practice_item_ids` instead of
  `practice_ref?`).
- §10: pointed to the real V1-V10 implementation and recorded the two
  additive validator checks from the phase brief.
- New §16 (this file's own numbering, not design's §16): the full set of
  Phase 5 decisions — the G2 graph's node shape and its deliberate omission
  of design's `critique` node, patch mode as a capability without an HTTP
  route yet, candidate-ID enforcement at parse time as well as validation
  time, the Planner Agent's no-embedded-fallback decision, and the two
  additive validator rules' hard/soft split.

`docs/ARCHITECTURE_CONTRACTS.md` §2, §3, §6, §9, and a new §17 added this
phase (Phase 8, Assessment/Mastery/Struggle Detection):
- §2: pointed to `backend/app/agents/assessor.py` as the Assessor Agent
  implementation, and `backend/app/assessment/mastery.py`/`struggle.py` as
  the Mastery Updater/Struggle Classifier implementations; noted
  `resolution.py`'s misconception state machine is deterministic and
  explicitly not the Reflection Agent.
- §3: recorded that the Mastery Updater is now implemented and that `MET`
  from assessed evidence alone (design §13.4's worked example) is now
  actually reachable, resolving the note Phase 4 left open.
- §6: noted `AssessmentResult`/`StruggleSignal` now have real field lists.
- §9: recorded the addition of `Assessment`/`StruggleSignal`/
  `LearnerMisconception`/`PracticeSession` (migration `0005_assessment`) to
  design §28's conceptual table list.
- New §17 (this file's own numbering, not design's §17): the full set of
  Phase 8 decisions — the deliberate scope boundary against the full
  Reflection Agent, mastery-as-estimate-never-fact, the accumulate-vs-reseed
  tier-upgrade difference from Phase 2, the Struggle Classifier's
  precedence/corroborating-signal rules, invented-misconception-tag
  rejection at parse time, `grade_mcq`'s never-trust-the-client posture,
  short-answer grading's degrade-to-ungraded behavior, and the deterministic
  (not Planner-Agent-routed) remediation-application decision.

`docs/ARCHITECTURE_CONTRACTS.md` §2, §12, §17, and a new §18 added this
phase (Phase 9, Reflection & Re-planning):
- §2: recorded the Reflection Agent (A4) mode (b) and the Reflection
  Validator as now implemented; mode (a) (plan critique) remains open.
- §12: `reflection/` recorded as a package-naming addition (alongside
  Phase 3's `catalog/`, Phase 6's `retrieval/`).
- §17: updated the Phase 8 scope-decision bullet to note it is superseded —
  `resolution.py` itself is unchanged, but is no longer the primary path;
  it is now Reflection's last-resort fallback.
- New §18 (this file's own numbering, not design's §18): the full set of
  Phase 9 decisions — the project-specific closed operator set vs. design
  §20.5's, deterministic (never LLM) root-cause identification, why
  Reflection bypasses `patch_existing_plan` rather than calling it, the
  fresh-`item_id`-on-carry-forward rule, the four-rung fallback ladder, the
  generalized trigger set, and the new Revert endpoint.

`docs/ARCHITECTURE_CONTRACTS.md` §2, §6, and a new §19 added this phase
(Phase 10, Tutor, Progress Reports and Provenance):
- §2: recorded the Tutor Agent (A5) as now implemented — all five LLM
  agents now exist — and the Report Builder/Provenance Service as now
  implemented, deterministic services.
- §6: noted `ProgressReport` now has a real field list (plus its three new
  supporting sub-models).
- New §19 (this file's own numbering, not design's §19): the full set of
  Phase 10 decisions — G4 as a real bounded LangGraph (unlike G3, since it
  has no interleaved-write problem), rule-based `classify_intent`/
  `plan_tools` over an LLM-driven tool loop and why that makes "bounded tool
  steps" a construction guarantee, citation verification as a distinct step
  from the agent's own schema-validation retry, the conservative answer's
  grounded-by-construction design, why the Tutor never drafts a plan
  override this phase, and why `/chat` is plain JSON rather than SSE.

### Next Phase

**After Phase 12 (all phases implemented):** the recommended next task is the planner's segment
splitting for long resources (see Known Issues, first Phase 12 bullet) - it is the largest remaining quality
gap and the only limitation that visibly hurts the demo. After that: attach a real `LLM_PROVIDER` and tune
prompts/schemas with the evaluation harness (`tests/evaluation`) as the regression net; replace the
placeholder session cookie with real auth; run `scripts/validate_links.py`; human-review the curated
content; run `docker compose up --build` and the Playwright suite on a healthy Docker.

**After Phase 11:** the frontend is feature-complete for the journey. Known follow-ups: (1) the
deterministic planner yields a thin week for the demo learner (most skills BLOCKED behind unmet
prerequisites; a real LLM or richer candidate set would improve it); (2) Starlette's 500 responses
carry no CORS headers (see §20); (3) reload the 21st MCP tools in a new session and run a component
research pass; (4) a Docker Compose run of the frontend against Postgres was not repeated this phase
(dev verification used SQLite; Postgres behaviour of the new read endpoints is dialect-portable SQL).

**Observability / evaluation / polish** (design §39.1's Phase 10 — this
project has no separate number for it, since this project's own Phase 10
was "Tutor," design's Phase 9). With all five LLM agents now real, this is
the last unimplemented phase in design §39.1's table. Candidates per design
§32/§33/the Agent Trace panel notes: a CI/nightly job scoring validator
soft-violation rates, reflection false-positive rate, and citation-existence
rate as evaluation metrics (needs an evaluation harness that doesn't exist
yet); the Postgres-backed LLM Gateway replay cache (Phase 1's open item, now
overdue with five real agent calls); a frontend Agent Trace panel /
gap-graph visualization consuming the trace events and graph data every
backend phase already exposes; the human review pass over curated content
(Phase 3) and the live link-validation sweep (Phase 6) before any live demo.

Still open on **Phase 3**: a human review pass over the curated content
(§11.5) — every edge/resource/misconception/item still shows
`reviewed_by: "edupath-phase3-curation"`, a placeholder; fold in the
key-option-carries-a-misconception-tag data quirk Phase 8 found (see
"Known Issues"). The live link-validation sweep itself is now implemented
(`scripts/validate_links.py`, Phase 6) but has not been *run* this session
(no network access in this environment) — run it before trusting
`link_status` in a demo.

Still open on **Phase 2**: a Postgres-backed LLM Gateway replay cache (now
overdue — the Profiler, Planner, and Assessor are all real agent calls);
wiring Phase 2's per-request `SkillNormalizer`/`DeterministicClaimExtractor`
construction onto the startup-loaded graph cache Phase 4 introduced; true
multi-file document upload (currently one file per call).

Still open on **Phase 4**: the `no_open_misconceptions_for(skill)`
acceptance-criteria clause — a per-learner misconception status table now
exists (`LearnerMisconception`, Phase 8), but nothing wires it into
`LearningObjective.acceptance_criteria` yet; the skill-dispute endpoint
(design §12.4, `POST /api/learners/me/skills/{skill_id}/dispute`);
`LearningObjective.est_minutes_low/high` — still not wired even though the
Gap Engine, Resource Retriever, and Planner are all in scope together now.

Still open on **Phase 6**: ranking weights are unvalidated hand-set
defaults (design §32's evaluation set doesn't exist yet); the live
web-search provider behind `WebFallbackGateway` is unimplemented (optional
per the phase brief); `learner_history`/`ResourceUsageRecord` is now
sourceable in principle (`assessments` exists, Phase 8) but nothing builds
it from that table yet.

Still open on **Phase 5**: `POST /api/plans/{id}/override` and
`GET /api/plans/{id}/revisions` (design §27) are still not implemented —
`patch_existing_plan` exists as a service-layer capability with no HTTP
caller (Reflection, Phase 9, bypasses it — see ARCHITECTURE_CONTRACTS.md
§18); the one-click Revert half of design §27's row *is* now implemented,
just under a different path
(`POST /api/learners/me/plans/{plan_id}/revisions/{revision_id}/revert`,
Phase 9) than design's table shows. No CI/nightly job runs the
deterministic Plan Validator's soft-violation rates as an evaluation metric
(design §17.3, needs design §32's evaluation harness).

Still open on **Phase 8**: `missing_prerequisite`'s direct-probe evidence
source is unwired (a real prior assessment on the prerequisite skill exists
in the data but nothing queries it, see "Known Issues"); no
`LearningActivity` table yet, so overload's `planned_vs_actual_ratio`/
`completion_rate` stay caller-supplied; `Assessment` generation coverage is
still the Phase 3 initial bank (95 items / 23 skills — notably,
`skill.chain_rule` has no `purpose="resolution-check"` items, so Phase 9's
wow-scenario probe carries zero practice items in this environment, see
"Known Issues"); a `CatalogRepository.replace_all()` re-ingestion story that
tolerates real learner-scoped FK rows (see "Known Issues") — needed before
this project can safely re-seed a catalog against a database with real
users on it.

Still open on **Phase 9**: Reflection Agent mode (a) (plan critique, design
§16.3 point 7 — soft pedagogical review after `validate_plan` passes but
before commit, in the G2 graph) is not implemented, only mode (b)
(evidence-triggered); design §20.8's automatic "deferred items reinstated"
step on misconception resolution is not implemented — `record_probe_result`
still only flips `LearnerMisconception.status`, nothing pulls a
previously-`DEFER`red item back to an earlier day_slot when its probe
passes; `cognitive_overload` triggers a bare `DEFER`, not yet wired into the
Plan Validator's V9 `overload_active` flag for the *next* `create_plan`
call (both already accept the flag, Phase 5 — this phase's Reflection path
doesn't set it either); no CI/nightly job evaluates reflection quality
(design §32's "false-positive reflection rate" metric needs an evaluation
harness that doesn't exist yet); high-impact-change user confirmation
(design §20.7: "dropping a role-critical skill... requires user
confirmation") is not implemented — every approved patch commits
immediately.

Still open on **Phase 10**: the Tutor never drafts a plan override at all
(design §23.3's "offer an override... explicit API call after the user
confirms" — not implemented, see "Known Issues"); no chat-turn/session
memory persistence (design §21's "session memory," see "Known Issues");
`/chat` is plain JSON, not design §27's SSE stream; `classify_intent`'s
skill-mention matching is a literal (word-boundary) scan, so a question that
names a skill only by an unlisted synonym falls back to `out_of_scope` or a
generic bucket rather than resolving it — the same class of limitation
`DeterministicClaimExtractor` (Phase 2) already accepts for the same reason.

### Exact Next Task

Every phase in design section 39.1 is implemented. The remaining work is quality and verification, in
priority order (details and numbers: `docs/FINAL_IMPLEMENTATION_STATUS.md`):

1. **Verify deployment on a healthy Docker Desktop:** `docker compose up --build`, then
   `docker compose exec api python scripts/run_journey.py --iterations 3` (add `--demo-seed` with
   `DEMO_MODE=true`), then the Playwright suite. This was the one Phase 12 item that could not be verified.
2. **Planner segment splitting** for resources longer than the session cap (coverage at the 45-minute
   default is 56%; a 20 h/week learner gets ~45 minutes). Touches `retrieval/ranker.py`'s `duration_ok`, the
   fallback planner, and V2/V6/duplicate rules in `planning/validator.py`. Re-run
   `tests/evaluation` - the utilization and coverage rows are the acceptance test.
3. **Attach a real `LLM_PROVIDER`** and tune the five agents' prompts/schemas against the evaluation
   harness; record a demo run (`DEMO_MODE=true` records) and verify `REPLAY_MODE=true` reproduces it.
4. **Real authentication** (signed session, login, CSRF) replacing the placeholder cookie.
5. Run `python scripts/validate_links.py` (needs network), and do the human review pass over the curated
   graph/catalog/item bank; extend the item bank (23 of 158 skills; 8 of 18 misconceptions cannot be
   confirmed; `skill.chain_rule` has no `resolution-check` item).
6. Carry-overs: design 20.8 "deferred items reinstated", Reflection plan-critique mode, Tutor-drafted
   overrides + `POST /plans/{id}/override`, skill-dispute endpoint, `DELETE /learners/me`, streamed chat and
   chat-turn persistence, `est_minutes_low/high` on objectives, the `no_open_misconceptions_for` acceptance clause.

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

# Phase 12: evaluation report, security suite, journey smoke/benchmark against a running stack
cd backend && python -m pytest tests/evaluation tests/security tests/integration -q   # writes reports/evaluation_metrics.md
python scripts/run_journey.py --base-url http://localhost:8000 --iterations 3            # add --demo-seed with DEMO_MODE=true
DEMO_MODE=true python scripts/seed_demo.py --preflight

# Full stack (from repo root; requires Docker Desktop running)
docker compose up -d --build
curl http://localhost:8000/api/health
curl -o /dev/null -w "%{http_code}\n" http://localhost:3000/dashboard
docker compose down
```
