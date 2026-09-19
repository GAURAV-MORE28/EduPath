# EduPath — Implementation State

> **Read this file first.** It is the canonical handoff for any Claude Code session
> resuming work on EduPath. It is optimized for fast orientation, not narrative detail —
> for the "why", see `docs/EduPath_System_Design.md` (authoritative) and
> `docs/ARCHITECTURE_CONTRACTS.md` (stable contracts).

---

### Current Phase

**Phase 1 — Foundation. Complete.**
**Phase 3 — Skill Graph + Catalog Engine. Implemented (Postgres tables,
NetworkX loader, graph validation/versioning, traversal queries, catalog
ingestion, retrieval-preparation infra). Human review pass over the curated
content itself is still outstanding — see "Domain Knowledge Pack" below.**

### Overall Project Status

Foundation layer implemented and verified end-to-end: FastAPI backend, Next.js
frontend, PostgreSQL + pgvector via Alembic migrations, a LangGraph
orchestration skeleton, and a Docker Compose stack that builds and runs all
three services together.

The **Skill Graph + Catalog Engine** (Phase 3, design §11/§12/§15) is now
implemented: the domain knowledge pack (`data/`, curated offline) loads into
Postgres via a validated ingestion pipeline, and a NetworkX graph built from
those tables answers prerequisite/ancestor/descendant/role-subgraph/
path-explanation queries. This is deterministic infrastructure only — no
learner-specific logic (profiling, gap analysis, planning, assessment,
reflection, tutor) exists yet, by design (see this phase's explicit "DO NOT
IMPLEMENT: skill-gap engine, planner, agents, reflection").

### Completed Phases

| Phase (per design §39.1) | Status |
|---|---|
| 0 — Engineering state protocol | ✅ Done |
| 1 — Foundation (repo skeleton, Docker Compose, FastAPI, Postgres schema, LLM Gateway, Trace Emitter, Next.js shell) | ✅ Done |
| 2 — Learner profiling | ❌ Not started |
| 3 — Skill graph + catalog (critical path) | ✅ Implemented (Postgres tables, NetworkX loader, validation, versioning, traversal queries, catalog ingestion, resource embeddings + FTS index). Curated content itself still needs a human review pass (§11.5) before production gap analysis trusts it. |
| 4 — Gap analysis | ❌ Not started |
| 5 — Planner | ❌ Not started |
| 6 — Resource retrieval | ❌ Not started |
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

### Files Created / Modified

**Backend** (`backend/`):
- `pyproject.toml`, `alembic.ini`, `pytest.ini`, `Dockerfile`, `.dockerignore`
- `app/__init__.py`, `app/main.py`, `app/config.py`, `app/logging_config.py`
- `app/core/__init__.py`, `app/core/errors.py`
- `app/schemas/__init__.py`, `app/schemas/envelope.py`, `app/schemas/common.py`
- `app/db/__init__.py`, `app/db/base.py`, `app/db/session.py`,
  `app/db/models.py` (extended, Phase 3 — see below)
- `app/db/migrations/env.py`, `app/db/migrations/script.py.mako`,
  `app/db/migrations/versions/0001_foundation.py`,
  `app/db/migrations/versions/0002_skill_graph_catalog.py` (new, Phase 3)
- `app/gateway/__init__.py`, `app/gateway/llm_gateway.py`,
  `app/gateway/embedding_gateway.py` (new, Phase 3)
- `app/orchestration/__init__.py`, `app/orchestration/state.py`,
  `app/orchestration/graphs.py`
- `app/agents/__init__.py`, `app/agents/base.py`, `app/agents/profiler.py`,
  `app/agents/planner.py`, `app/agents/assessor.py`,
  `app/agents/reflection.py`, `app/agents/tutor.py`
- `app/services/__init__.py`
- `app/repositories/__init__.py`, `app/repositories/user_repository.py`,
  `app/repositories/catalog_repository.py` (new, Phase 3)
- `app/graph/__init__.py`, `app/graph/loader.py`, `app/graph/queries.py`,
  `app/graph/validation.py` (new package, Phase 3)
- `app/catalog/__init__.py`, `app/catalog/ingest.py` (new package, Phase 3)
- `app/sse/__init__.py`, `app/sse/trace.py`
- `app/api/__init__.py`, `app/api/deps.py`
- `app/api/v1/__init__.py`, `app/api/v1/router.py`, `app/api/v1/health.py`,
  `app/api/v1/runs.py`
- `scripts/seed_catalog.py` (new, Phase 3 — CLI catalog ingestion entrypoint)
- `tests/__init__.py`, `tests/conftest.py` (extended: `catalog_session`
  fixture, Phase 3), `tests/test_health.py`, `tests/test_db_connection.py`,
  `tests/test_langgraph_init.py`, `tests/test_graph_validation.py`,
  `tests/test_catalog_ingest.py`, `tests/test_graph_loader.py`,
  `tests/test_graph_queries.py`, `tests/test_embedding_gateway.py` (all five
  new, Phase 3)

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
**networkx (Phase 3, new — the graph engine per design §34).**
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
the default and the gateway degrades deterministically.

### Database Status

Postgres 16 + pgvector, running via Docker Compose, migrated with Alembic.
Two migrations: `0001_foundation` (`vector`/`pg_trgm` extensions, `users`)
and `0002_skill_graph_catalog` (`skills`, `skill_edges`, `roles`,
`role_requirements`, `misconceptions`, `resources`, `resource_skills`,
`practice_items`, `graph_meta`, plus a generated `resources.search_vector`
tsvector column with a GIN index). Both verified this session against a real
Postgres 16 + pgvector container: upgrade, downgrade, and re-upgrade all ran
clean, and `backend/scripts/seed_catalog.py` populated the full 158-skill
domain pack (158 skills, 3 roles, 203 edges, 140 resources, 18
misconceptions, 95 items) with FTS and pgvector cosine-similarity queries
both confirmed working end-to-end.

No other table in the conceptual schema (`LearnerProfile`, `Document`,
`Evidence`, ...) exists yet — each is created by the migration the owning
phase adds.

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

Two endpoints implemented: `GET /api/health`, `GET /api/runs/{run_id}/events`
(SSE). None of the learner-scoped endpoints in design §27's table exist yet.
Phase 3 deliberately added no API routes — `SkillGraphService` and
`CatalogRepository` are internal services with no HTTP surface yet; the first
route that needs them (most likely Gap Analysis's role-subgraph/explanation
queries) is Phase 4's to add.

### Agent Status

All five LLM agents exist as classes with the shared `Agent` interface, each
raising `NotImplementedError`. No LangGraph business graphs (G1-G4) exist —
only the bootstrap graph used to prove the framework. No agent has tool
access. Phase 3 added no agents (it is 100% deterministic services, per
ARCHITECTURE_CONTRACTS.md §2).

### Tests Status

Backend: **54 tests, all passing** (`backend/tests/`) — run with
`cd backend && python -m pytest -q`. Phase 1's original 5 (health endpoint
shape; DB session + `UserRepository` round-trip; LangGraph bootstrap graph
compiles and runs to `status="completed"`) plus Phase 3's 49 (graph
invariants, catalog ingestion against the real domain pack, NetworkX graph
loading, prerequisite/role-subgraph/path-explanation queries, embedding
gateway determinism — see the Phase 3 "Tests" bullet under "Completed Work"
above for the breakdown). All run against SQLite (`tests/conftest.py`'s
existing dialect-portability convention); the Postgres-only paths
(`CatalogRepository.search_resources_by_text`/`search_resources_by_vector`,
the generated `search_vector` column) were verified manually this session
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
  for Phase 1 (design doc does not specify an auth provider) but any
  learner-scoped router added in Phase 2+ must not rely on this beyond the
  boundary shape.
- The LLM Gateway's replay cache is in-process only (`InMemoryReplayCache`),
  not yet backed by a Postgres table. ARCHITECTURE_CONTRACTS.md §14 requires
  a durable record/replay cache — implement the Postgres-backed version
  alongside the first real agent call (Phase 2, Profiler).
- No CI pipeline exists to run backend tests / frontend build / compose
  startup automatically on push.
- Docker Desktop must be running before `docker compose up`; if its engine
  is stopped, compose fails at the daemon connection (not a config issue —
  `docker compose config` validates independent of the daemon).
- The Skill Graph is not yet loaded at app startup (`app/main.py`'s
  `lifespan`) — Phase 3 built the loader but nothing calls it yet, since no
  API route or agent needs the graph in-process until Phase 4. Wire this in
  alongside Phase 4's first real caller rather than loading it speculatively
  now.
- `CatalogRepository.search_resources_by_text`/`search_resources_by_vector`
  raise `NotImplementedError` under SQLite (Postgres-only SQL/operators) —
  by design, but it means the automated test suite cannot exercise them; they
  were only verified manually against a live Postgres container this
  session, not via `pytest`. Re-verify manually after touching either method
  until the project has a Postgres-backed CI tier.

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

### Contract Changes

`docs/ARCHITECTURE_CONTRACTS.md` §5 and §9 updated this phase (see that
file's diff for exact wording):
- §5: recorded that the Postgres tables + NetworkX loader described as
  "Phase 4+ work" in the previous entry are now implemented, and named the
  files (`app/catalog/ingest.py`, `app/graph/loader.py`,
  `app/graph/queries.py`).
- §9: recorded two **additions** to design §28's conceptual data model — the
  `GraphMeta` table (graph-version history; §28 doesn't list it, but §5's
  "graph is versioned" and §14's "record graph_version" need a home for that
  version history) and a handful of extra columns
  (`Misconception.remediation_candidates`, `PracticeItem.purpose`/
  `explanation`/`generated_by`/`validated_by`/`graph_version`) that carry
  source/review metadata and the `REMEDIATED_BY` edge target list from the
  domain-pack JSON. Also recorded the `JSON`-over-`ARRAY` dialect-portability
  decision. None of this contradicts §28 (which says "only fields that are
  actually used are listed") or any other stable contract.

### Next Phase

**Phase 4 — Gap analysis** (design §39.1, §13): the deterministic Gap Engine
(`analyze_gaps(role, learner, graph)`, design §13.3) that compares the
target-role subgraph (`SkillGraphService.role_subgraph`, now implemented)
against a learner's evidence/mastery to produce `SkillGap[]`
(MET/WEAK/UNVERIFIED/MISSING/BLOCKED), `strengths[]`, `audit_flags[]`, and
`LearningObjective[]`. Needs Phase 2 (Learner profiling — not started) to
exist first for real learner evidence to analyze against, or can be built
and tested against the seeded demo learner state
(`data/dataset/demo/demo_learner_state.json`) in the meantime. This is also
where the NetworkX graph gets wired into `app/main.py`'s startup lifespan for
the first time (see "Known Issues" above).

Phase 2 (Learner profiling) remains not started and is not blocked by
anything in this phase; it can proceed independently, now with
`data/dataset/skills.json`'s aliases available (loaded into Postgres) for the
Skill Normalizer.

Still open on **Phase 3** itself (does not block Phase 4, but should happen
before this graph is trusted in a real demo): a human review pass over the
curated content (§11.5) — every edge/resource/misconception/item still shows
`reviewed_by: "edupath-phase3-curation"`, a placeholder — and a live
HEAD-request link-validation sweep over the 140 resource URLs (`link_status`
is currently a spot-check, not a full crawl).

### Exact Next Task

1. For Phase 4 code: implement the Gap Engine as a deterministic service
   (`app/gap/`, per ARCHITECTURE_CONTRACTS.md §12's package-naming
   convention) implementing design §13.3's `analyze_gaps` algorithm on top of
   `SkillGraphService.role_subgraph`/`hard_ancestors`/`topological_layers`
   (all implemented, Phase 3); add the `LearnerSkillState`,
   `LearnerMisconception` tables (design §28) + migration for the learner
   overlay (design §12.1) the Gap Engine reads; add `GET
   /api/learners/me/gaps` (or similar, per design §27); wire `GraphLoader`
   into `app/main.py`'s lifespan so the NetworkX graph is loaded once at
   startup rather than per-request.
2. If Phase 2 (Learner profiling) isn't done first, build/test Phase 4
   against the seeded demo learner state
   (`data/dataset/demo/demo_learner_state.json`) so Gap Engine work isn't
   blocked on Profiler work landing first.
3. Before trusting this graph in a live demo: run the human review pass and
   live link-validation sweep noted above (Phase 3 remaining work).

### Commands To Verify Current State

```bash
# Domain knowledge pack (from repo root; stdlib-only, any Python 3.9+)
python data/scripts/build_dataset.py
python data/scripts/validate_dataset.py

# Backend tests (from backend/, with .venv activated or via pip install -e ".[dev]")
cd backend && python -m pytest -q

# Frontend build
cd frontend && npm run build

# Skill graph + catalog migration and seed (from backend/; requires a running,
# reachable Postgres — e.g. `docker compose up -d postgres` from repo root)
cd backend && alembic upgrade head
python scripts/seed_catalog.py

# Full stack (from repo root; requires Docker Desktop running)
docker compose up -d --build
curl http://localhost:8000/api/health
curl -o /dev/null -w "%{http_code}\n" http://localhost:3000/dashboard
docker compose down
```
