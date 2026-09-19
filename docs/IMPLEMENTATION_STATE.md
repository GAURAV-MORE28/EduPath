# EduPath — Implementation State

> **Read this file first.** It is the canonical handoff for any Claude Code session
> resuming work on EduPath. It is optimized for fast orientation, not narrative detail —
> for the "why", see `docs/EduPath_System_Design.md` (authoritative) and
> `docs/ARCHITECTURE_CONTRACTS.md` (stable contracts).

---

### Current Phase

**Phase 0 — Project Initialization / Engineering State Protocol.**
No application phase (Section 39.1 of the system design: Phases 1–10) has started.

### Overall Project Status

Design-complete, code-not-started. The system design document
(`docs/EduPath_System_Design.md`, v1.0) is implementation-ready and authoritative.
This session established state tracking, contract tracking, changelog and README so
future sessions can work incrementally without re-deriving architecture from the
2300-line design doc each time.

### Completed Phases

| Phase (per design §39.1) | Status |
|---|---|
| 0 — Engineering state protocol (this) | ✅ Done |
| 1 — Foundation (repo skeleton, Docker Compose, FastAPI, Postgres schema, LLM Gateway, Trace Emitter, Next.js shell) | ❌ Not started |
| 2 — Learner profiling | ❌ Not started |
| 3 — Skill graph + catalog (critical path) | ❌ Not started |
| 4 — Gap analysis | ❌ Not started |
| 5 — Planner | ❌ Not started |
| 6 — Resource retrieval | ❌ Not started |
| 7 — Practice + assessment | ❌ Not started |
| 8 — Reflection / re-planning (core differentiator) | ❌ Not started |
| 9 — Tutor | ❌ Not started |
| 10 — Observability / evaluation / polish | ❌ Not started |

### Current Phase Status

Phase 0 is complete as of this commit. No source code exists yet.

### Completed Work

- Read and indexed `docs/EduPath_System_Design.md` (v1.0, 42 sections + appendices).
- Created `docs/IMPLEMENTATION_STATE.md` (this file).
- Created `docs/ARCHITECTURE_CONTRACTS.md` (stable contracts extracted from the design doc).
- Created `docs/CHANGELOG.md` (empty log, ready for Phase 1 entries).
- Created root `README.md`.
- Initialized git repository and made the first commit.

### Files Created / Modified

- `docs/IMPLEMENTATION_STATE.md` (new)
- `docs/ARCHITECTURE_CONTRACTS.md` (new)
- `docs/CHANGELOG.md` (new)
- `README.md` (new)
- `docs/EduPath_System_Design.md` (pre-existing, unmodified — authoritative source)
- `research_papers/*.pdf` (pre-existing, unmodified — reference material, not re-read this session per the design doc's own note in its header)

### Dependencies Installed

None. No `pyproject.toml`, `requirements.txt`, `package.json`, or `docker-compose.yml`
exists yet. Phase 1 must create these.

### Environment Variables Required

None yet configured. Per design §35 (Deployment Architecture), Phase 1 must define:
- LLM/VLM provider API keys (via the LLM Gateway; provider-agnostic, 3 tiers: small/mid/strong)
- `REPLAY_MODE`, `DEMO_MODE` feature flags
- Postgres connection string (with pgvector extension enabled)
- GitHub REST API token (read-only, for `github_repo_summary` tool)
- Object storage config (local volume for dev, or S3-compatible bucket)
- Tunable thresholds (mastery cut-offs, load caps, ranking weights — see design §10.4, §17.2)

No `.env.example` exists yet — create one in Phase 1.

### Database Status

Not created. No Postgres instance, no migrations, no schema applied. Conceptual schema
is fully specified in design §28 (Data Model) — see `ARCHITECTURE_CONTRACTS.md` for the
authoritative table list. pgvector and Postgres FTS extensions will be required.

### Data Assets Status

- **Skill graph** (~150–250 skills, 3 roles, prerequisite edges, misconception catalog):
  **not started.** This is the critical-path, highest-labor item (design §39.2 —
  "Hard (labor)", largest schedule risk). Must be LLM-drafted then human-reviewed.
- **Resource catalog** (~100 entries): not started.
- **Item bank** (assessment items, ≥ 6 per assessable skill): not started.
- Research papers backing the design are present in `research_papers/` but were not
  re-read for the design doc (see its header note) and are reference-only.

### API Status

Not implemented. Full endpoint contract is specified in design §27 and mirrored in
`ARCHITECTURE_CONTRACTS.md`. No FastAPI app exists yet.

### Agent Status

None of the 5 LLM agents (Profiler, Planner, Assessor, Reflection, Tutor) or 10
deterministic services (design §7) are implemented. No LangGraph graphs
(G1 Onboarding, G2 Planning, G3 Evidence-Response, G4 Tutor) exist.

### Tests Status

No test suite exists. Design calls for pytest + a small eval harness + simulated
learners (§34, §32).

### Known Issues

None — no code exists to have issues.

### Architectural Decisions

None made beyond what `docs/EduPath_System_Design.md` already specifies (see its
§41 Final Architecture Decisions and D1–D25 decision log). This session made **no**
new architectural decisions and introduced **no** deviations from the design doc.

### Contract Changes

None. `docs/ARCHITECTURE_CONTRACTS.md` was newly created this session by extracting
(not inventing) stable contracts already present in the design doc.

### Next Phase

**Phase 1 — Foundation** (design §39.1): repo skeleton, Docker Compose (`web`, `api`,
`postgres`), FastAPI skeleton, Postgres schema + migrations, LLM Gateway (provider
tiers, structured-output schemas, record/replay cache), Trace Emitter + SSE, Next.js
shell. Effort estimate in the design: ~10 person-hours.

Note: design §39.1 says **Phase 3 (skill graph + catalog curation) should start on
day one in parallel with Phase 1**, since it is content/labor work on the critical
path (1 → 3 → 4 → 5 → 7 → 8), not code.

### Exact Next Task

Start Phase 1 foundation work:
1. Scaffold the FastAPI backend (Python 3.11+, Pydantic v2) with the module layout
   from design §35: `profiling/`, `graph/`, `gap/`, `planning/`, `assessment/`,
   `reflection/`, `tutor/`, `provenance/`, `gateway/`.
2. Scaffold the Next.js frontend shell.
3. Write `docker-compose.yml` for `web`, `api`, `postgres` (with pgvector).
4. Create the Postgres schema/migrations from design §28 (see `ARCHITECTURE_CONTRACTS.md`
   for the table list).
5. Build the LLM Gateway stub (tiering, schema validation, record/replay table).
6. In parallel: begin skill-graph curation for the first role (recommend starting with
   Machine Learning Engineer, per the design's worked demo persona in §13.4).

Do not start Phase 2+ work before Phase 1's schema and gateway exist — later phases
depend on them.

### Commands To Verify Current State

```bash
# Confirm no application code exists yet (expected: only docs/ and research_papers/)
ls -la

# Confirm git state
git log --oneline
git status

# Once Phase 1 exists, this file's "Commands To Verify" section should be replaced with
# real build/test/run commands (e.g., docker compose up, pytest, npm run dev).
```
