# EduPath — Changelog

All notable changes to the EduPath project are recorded here, newest first.
This is an engineering changelog (what changed and why it matters for
implementation state), not a marketing changelog.

Format per entry: `## [Phase N | date] Short title` followed by a short bullet list.

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
