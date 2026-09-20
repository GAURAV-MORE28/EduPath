# EduPath — Architecture Contracts

> Stable, load-bearing contracts extracted from `docs/EduPath_System_Design.md` (v1.0,
> authoritative). This file records only what is settled — not implementation
> narrative. When the design doc and this file disagree, **the design doc wins**;
> fix this file to match it.
>
> Every future PR that touches a contract listed here must update this file in the
> same change, and add an entry to `docs/CHANGELOG.md`.

---

## 1. Core architectural style

- **Modular monolith.** One FastAPI process + one Next.js app + one PostgreSQL
  instance. No microservices, no separate vector DB, no Neo4j, no task-queue service.
- **LLMs propose, deterministic code disposes** (P1). Every LLM output is
  schema-validated, then rule-validated, before it can change persisted state.
- **Explicit state over emergent behavior** (P4). Orchestration is LangGraph state
  machines with a Postgres checkpointer — not free-form agent swarms, not AutoGen/CrewAI.
- **Bounded autonomy** (P6). Hard caps everywhere: retries ≤ 2, reflection rounds ≤ 2,
  planner attempts ≤ 4 before fallback, tutor tool steps ≤ 4, per-run token/wall-clock
  budgets, revision cooldown (default 24h) per (learner, skill).
- **Graceful degradation** (P7). Every LLM-dependent step has a deterministic or
  cached fallback. A demo/run must never hard-fail because an LLM call failed.

## 2. The five LLM agents (and nothing else is an LLM agent)

| Agent | Mode(s) | Can mutate persisted state directly? | Implemented |
|---|---|---|---|
| **Profiler** | single | No — emits `ExtractedClaims` only | ✅ Phase 2 (`backend/app/agents/profiler.py`) |
| **Planner** | draft / patch | No — writes only via validated commit nodes | ✅ Phase 5 (`backend/app/agents/planner.py`) |
| **Assessor** | generation (strong) / grading & validation (small) | No | ✅ Phase 8 (`backend/app/agents/assessor.py`) |
| **Reflection** | (a) plan critique, (b) evidence-triggered | No — emits operators only | ✅ Phase 9, mode (b) only (`backend/app/agents/reflection.py`); mode (a) plan critique ❌ |
| **Tutor** | read-only | No — cannot mutate the plan; may only propose an override the user confirms | ✅ Phase 10 (`backend/app/agents/tutor.py`) — proposing/applying an override is still ❌, see §19 |

Everything else (Gap Engine, Skill Normalizer\*, Skill Graph Service, Resource
Retriever/Ranker, Plan Validator, Fallback Planner, Mastery Updater, Struggle
Classifier, Reflection Validator, Report Builder, Provenance Service, Trace Emitter)
is a **deterministic service**. No new LLM agents may be added without updating this
file and justifying the addition against design §8.1's role-by-role table.

**Report Builder and Provenance Service implemented (Phase 10):**
`backend/app/tutor/report_builder.py`'s `build_progress_report()` and
`backend/app/provenance/citations.py`'s `verify_citations()` — both pure
functions, no LLM call in either module (see §19 below). All five LLM agents
now exist.

\* Skill Normalizer uses a small LLM only for ambiguous-alias disambiguation; it is
not counted among the 5 agents. **Implemented (Phase 2):**
`backend/app/profiling/skill_normalizer.py`. **Resource Retriever/Ranker
implemented (Phase 6):** `backend/app/retrieval/ranker.py`'s `recommend()` —
no LLM call anywhere in the package (see §15 below). **Plan Validator and
Fallback Planner implemented (Phase 5):** `backend/app/planning/validator.py`'s
`validate_plan()` and `backend/app/planning/fallback.py`'s
`build_fallback_plan()` — both pure functions, no LLM call anywhere in either
module (see §16 below). **Mastery Updater and Struggle Classifier
implemented (Phase 8):** `backend/app/assessment/mastery.py`'s
`update_mastery()` and `backend/app/assessment/struggle.py`'s
`classify_struggle()` — both pure functions, no LLM call in either module
(see §17 below). The misconception resolution state machine
(`backend/app/assessment/resolution.py`) is likewise deterministic; it now
serves as the Reflection pipeline's last-resort guaranteed-safe patch
(Phase 9, see §17/§18) rather than being called directly from
`app/assessment/service.py`'s routing. **Reflection Agent mode (b) and the
Reflection Validator implemented (Phase 9):**
`backend/app/agents/reflection.py`, `backend/app/reflection/validator.py`
(deterministic, no LLM call) — see §18 below. Mode (a) (plan critique) is
still out of scope.

## 3. Evidence tiers (never conflate these)

Three classes of learner information are **never equivalent**: self-reported,
evidence, inference. Only evidence can satisfy a role requirement.

| Tier | Meaning | Default prior (successes/trials) |
|---|---|---|
| E0 | Self-reported / listed only | 0.5 / 1.0 |
| E1 | Documented in context (resume prose) | 1.0 / 1.5 |
| E2 | Artifact-verifiable (GitHub, certificate, portfolio) | 2.0 / 3.0 |
| E3 | Assessed in-system | Strongest; accumulates per item |

All numeric priors/thresholds here are **tunable engineering defaults**, not
empirical constants (see design doc's header note). Do not present them as derived.

**Tier gate for `MET`:** mastery ≥ threshold(L) **and** tier_max ≥ tier_required(L).
- L1 (Foundational) ≥ 0.50 mastery, min tier E1
- L2 (Working) ≥ 0.70 mastery, min tier E2 or E3
- L3 (Proficient) ≥ 0.85 mastery, min tier E3, `n_obs ≥ 3`

A self-report or inference alone can only ever produce `UNVERIFIED`, never `MET`.
**Implemented (Phase 4):** `backend/app/core/thresholds.py`'s
`LEVEL_MASTERY_THRESHOLD`/`LEVEL_TIER_REQUIRED`/`LEVEL_MIN_N_OBS`, consumed
by the Gap Engine's `_level_met` (`backend/app/gap/engine.py`). Note: this
project's evidence-tier priors (this section, above) cap the Beta-count
mastery *estimate* at 0.4 (E1/E2's `alpha/(alpha+beta)`) until real assessed
observations exist — so in practice, pre-assessment E1/E2 evidence lands
`WEAK` under this gate, not `MET`, even for a strong artifact like a GitHub
repo. `MET` from evidence alone (design §13.4's worked example) requires the
Mastery Updater to accumulate real assessed `alpha`/`beta`; this was an
intentional consequence of this section's fixed priors combined with §13.4
being an aspirational full-system illustration, not a Phase 4 defect — see
`docs/IMPLEMENTATION_STATE.md`'s Phase 4 "Architectural Decisions". **The
Mastery Updater is now implemented (Phase 8):**
`backend/app/assessment/mastery.py`'s `update_mastery()` — once a skill has
at least one *assessed* item, `tier_max` becomes `E3` and `alpha`/`beta`
accumulate per item (design §10.4's `α += w` / `β += w`), so `MET` becomes
reachable from real assessed evidence exactly as §13.4 describes; it
remains unreachable from E0-E2 evidence alone, which is the gate working as
specified, not a gap.

## 4. Skill-gap statuses

`MET | WEAK | UNVERIFIED | MISSING | BLOCKED`

- `UNVERIFIED` → triggers a **verify-before-teach probe**, not a lesson.
- `BLOCKED` → a *hard* prerequisite is `WEAK`/`MISSING`. An `UNVERIFIED` prerequisite
  does **not** block (it gets probed first).
- Gap analysis is 100% deterministic (Gap Engine). No LLM in the decision path — an
  LLM may only narrate the result afterward.
- **Implemented (Phase 4):** `backend/app/gap/engine.py`'s `analyze_gaps` —
  design §13.3's algorithm verbatim (required-level computation, the tier
  gate, the BLOCKED overlay, priority/topological layering), plus §12.4's
  three audit-flag types and §13.5's `LearningObjective` generation. A pure
  function over `SkillGraphService` (Phase 3) and two small
  framework-independent record types (no DB/gateway import in the module) —
  see that file's docstring. Exposed via `GET /api/learners/me/gaps`
  (`backend/app/api/v1/gap.py`), a bare deterministic-service call per design
  §27's table (no LangGraph run, matching that table's empty "Orchestrator"
  column for this endpoint).
- **Decided (Phase 4):** Gap analysis results (`SkillGap[]`/`LearningObjective[]`)
  are **computed on demand, not persisted** — no new Postgres tables were
  added this phase. Design §10.6's read/write matrix lists Gap Engine as
  writing these, but §12.1 already establishes the same "derived view, not
  stored, recomputed on demand" pattern for the target-role subgraph itself;
  this phase extends that pattern rather than introducing new tables, since
  recomputation is cheap (a NetworkX traversal over an in-memory graph) and
  `LearningObjective.objective_id` is a deterministic `obj.<role_id>.<skill_id>`
  string (`objective_id_for`), stable across calls without a table backing
  it. Revisit if a later phase (Planner) needs to reference a specific gap
  run's output after the underlying evidence has since changed.

## 5. Knowledge graph conventions

- **Node types (closed set):** Role, Skill, Misconception, Resource, PracticeItem.
  Certificate, LearningObjective, Learner, Evidence are deliberately **not** nodes —
  they live in relational tables as a learner overlay.
- **Edge types (closed set):** `PREREQUISITE_OF`, `PART_OF`, `REQUIRES`, `TARGETS`,
  `ASSESSES`, `MISCONCEPTION_OF`, `ROOTED_IN`, `REMEDIATED_BY`, `RELATED_TO`.
  `RELATED_TO` is explanation/normalization only — **never** used in planning or
  gap logic.
- Every edge carries `source` (`curated` / `llm_draft_reviewed` / `imported_candidate`)
  and `reviewed_by`. LLM-drafted edges must be human-reviewed before use.
- The hard-prerequisite subgraph **must be a DAG** (cycle check is a build-time
  invariant, design §11.5).
- Graph is curated offline, versioned (`graph_version`), loaded from Postgres into
  NetworkX at process startup. **The LLM cannot add graph edges at runtime.**
- If a requested role is not in the curated graph: return "role not supported".
  **Never invent a graph at runtime.**
- **Curated source data (Phase 3):** `data/` at the repo root holds the offline-curated
  skill graph, resource catalog, misconception catalog and assessment item bank as
  generated JSON (`data/dataset/`), with the curated content and a validator in
  `data/scripts/`. See `data/README.md`. Current `graph_version`: `v0.1.0-domain-pack`
  (158 skills / 3 roles / 203 skill-edges / 140 resources / 18 misconceptions / 95
  items — not yet human-reviewed per §11.5).
- **Postgres tables + NetworkX loader (Phase 3, implemented):** migration
  `0002_skill_graph_catalog` creates `skills`, `skill_edges`, `roles`,
  `role_requirements`, `misconceptions`, `resources`, `resource_skills`,
  `practice_items`, `graph_meta` (`backend/app/db/models.py`).
  `backend/app/catalog/ingest.py` validates (`backend/app/graph/validation.py`)
  then loads `data/dataset/*.json` into these tables (`replace_all`, one
  transaction per run — the curated graph is versioned and reloaded whole, not
  diffed row-by-row); run it with `backend/scripts/seed_catalog.py`.
  `backend/app/graph/loader.py` builds the in-process `networkx.MultiDiGraph`
  from those tables (all nine closed-set edge types materialized regardless of
  which table an edge's data lives in); `backend/app/graph/queries.py`
  (`SkillGraphService`) provides ancestor/descendant, topological-order,
  role-subgraph and prerequisite-path-explanation queries; also (Phase 4)
  `hard_prerequisite_out_edges` (min_level-aware) and `part_of_children`, both
  added for the Gap Engine below.
- **Wired into `app/main.py`'s startup lifespan (Phase 4, Gap Engine):** the
  graph is loaded once at process startup and cached on
  `app.state.skill_graph_service`. Best-effort, not fail-fast (unlike the
  LangGraph bootstrap check) — an empty/not-yet-seeded catalog is a normal
  pre-`seed_catalog.py` state, not a startup bug.
  `app/api/deps.py`'s `get_skill_graph_service` dependency reads that cache
  and falls back to a fresh per-request load when it's absent (e.g. the test
  suite's ASGI transport never drives the lifespan at all).

## 6. Agent I/O contract

- All inter-component messages are typed, schema-validated (Pydantic v2 /
  JSON-schema), wrapped in `AgentMessage { run_id, step_id, schema_name,
  schema_version, producer, created_at, payload, refs[] }`.
- Free text is allowed **only** in fields explicitly marked *display-only* and is
  never parsed by downstream components.
- Agents communicate **by ID**, resolved against the database. Unknown IDs → reject.
- Schema validation failure → retry with the error message, max 2 times, then
  degrade to a deterministic fallback. **Never loop silently.**
- Core schema names (see design §25.2 for full field lists): `LearnerState`,
  `SkillState`, `SkillGap`, `LearningObjective`, `ResourceRecommendation`,
  `WeeklyPlan`, `PlanItem`, `AssessmentResult`, `StruggleSignal`, `ReflectionResult`,
  `ReplanRequest`, `ProgressReport`. **`SkillGap`/`LearningObjective` implemented
  (Phase 4):** `backend/app/schemas/common.py`, real §25.2 field lists.
  **`ResourceRecommendation` implemented (Phase 6):** same file — no API
  route consumes it yet (see §15 below), but the schema itself is real.
  **`WeeklyPlan`/`PlanItem` implemented (Phase 5):** same file, real §25.2
  field lists — `PlanItem.practice_item_ids` is an addition beyond §25.2's
  single `practice_set_id?` (see §16 below for why). **`AssessmentResult`/
  `StruggleSignal` implemented (Phase 8):** same file, real §25.2 field
  lists — `AssessmentResult` also gained a supporting `AssessmentItemResult`
  sub-model for its `items[]` entries (see §17 below). **`ProgressReport`
  implemented (Phase 10):** same file, real §25.2 field list, plus
  `ProgressSkillEntry`/`StruggleAreaEntry`/`ProgressActivityEntry` supporting
  sub-models for its `acquired`/`in_progress`/`struggle_areas`/
  `completed_work`/`next_steps` entries (see §19 below).

## 7. IDs

- Every core entity has a stable, database-resolved ID (`learner_id`, `skill_id`,
  `role_id`, `plan_id`, `revision_id`, `evidence_id`, `decision_id`, `run_id`,
  `step_id`, etc. — see design §28 for the full entity list).
- `learner_id` is **always** derived from the session/auth context — **never**
  accepted as an argument from an LLM or from request body on learner-scoped
  endpoints. Tools given to LLM agents must not accept a learner identifier as an
  argument (design §26.2, §29).
- Resource IDs, skill IDs, and misconception IDs are catalog/graph-resolved — an
  LLM never emits a raw URL or invents an ID; it selects from a pre-built candidate
  ID set.
- **Decided (Phase 1):** UUID v4, stored as `String(36)`, for learner/run-scoped rows
  (`user_id` implemented this way in `backend/app/db/models.py`).
- **Decided (Phase 3):** Stable, human-readable slugs for curated graph/catalog rows —
  `skill.<name>` (e.g. `skill.chain_rule`), `role.<name>` (e.g. `role.ml_engineer`),
  `res.<name>`, `misc.<name>`, `item.<skill>.<n>` — implemented in `data/dataset/`.
  Demo/learner-scoped rows in the demo dataset follow the Phase 1 UUID-style
  convention loosely (readable fixed IDs like `demo-learner-asha`, since they are
  seed data, not real session-derived rows).

## 8. API conventions

- REST + Server-Sent Events (SSE); JSON bodies; session-based auth.
- Endpoint surface is namespaced under `/api/...`; learner-scoped routes use
  `/api/learners/me/...` and derive identity from the session.
- State-changing endpoints that touch the plan or learner-skill-state go through a
  LangGraph run (G1–G4) and produce trace events, never a bare CRUD write.
- SSE trace event shape: `{run_id, step_id, ts, agent_or_service, kind: input |
  tool_call | graph_query | retrieval | decision | validation | reflection | replan |
  output | degraded | error, summary, refs[]}`.
- Full endpoint table is design §27 — treat it as authoritative; do not invent
  endpoints that bypass validated commit nodes.

## 9. Database conventions

- **PostgreSQL for everything**: relational tables, graph tables (loaded into
  NetworkX at startup), pgvector for embeddings, Postgres FTS for keyword search,
  JSONB for flexible/structured fields (preferences, constraints, operators, diffs).
- Every learner-scoped table carries `learner_id` for row-level isolation.
- Table list is design §28 — do not add tables that duplicate data already owned by
  another table; prefer a JSONB column on an existing row if the design doc lists it
  that way (e.g., `preferences JSONB`, `constraints JSONB`, `options JSONB`).
- No Redis, no Neo4j, no separate vector DB. Cache is in-process + a Postgres
  record/replay table.
- **Decided (Phase 3):** list-valued columns (`Skill.aliases`,
  `Resource.prerequisite_skill_ids`, `Misconception.remediation_candidates`,
  `PracticeItem.options`) use the generic SQLAlchemy `JSON` type, not
  `postgresql.ARRAY`/`JSONB` — the same model then works against both
  Postgres (prod) and SQLite (tests), matching Phase 1's `User.consent_flags`
  precedent. `Resource.embedding`/`Skill.embedding` use pgvector's `Vector`
  type, which also round-trips under SQLite for storage (only its `<=>`
  distance operator is Postgres-only — see `CatalogRepository.search_resources_by_vector`).
- **Addition (Phase 3):** `GraphMeta` (append-only: one row per catalog
  ingestion run — `graph_version`, `loaded_at`, entity counts) is not in
  design §28's conceptual table list but is required by this section's
  "graph is versioned" and §14's "record graph_version in every
  DecisionRecord" — there was no other table to hold that version history.
  `Misconception.remediation_candidates` (→ `REMEDIATED_BY` edges) and
  `PracticeItem.purpose`/`explanation`/`generated_by`/`validated_by`/
  `graph_version` (source/review metadata carried over verbatim from the
  domain-pack JSON) are likewise additions beyond §28's field list, not
  contradictions of it (§28 says "only fields that are actually used are
  listed").
- **Addition (Phase 2):** `PendingClaim` (`backend/app/db/models.py`) is not
  in design §28's table list. It is the durable hand-off between a G1
  Onboarding run (`parse_documents -> extract_claims -> verify_evidence ->
  normalize_skills`) and the separate `POST /api/learners/me/claims/confirm`
  request — design's `RunState` (§9.2) would normally hold in-flight claims
  as checkpointed graph state, but no Postgres-backed LangGraph checkpointer
  exists yet (Phase 1 left this open; see IMPLEMENTATION_STATE.md "Known
  Issues"). Revisit once that checkpointer exists.
- **Addition (Phase 2):** `Document.type` includes `"github"` as a value,
  modeling a `github_repo_summary` result as a synthetic document (its
  `storage_ref` is the repo URL) rather than a separate evidence code path
  — this lets a GitHub-sourced claim flow through the same
  extract/verify/normalize pipeline as any other document, with
  `is_github_source=True` driving the Evidence Verifier's existing E2-tier
  rule (design §22.4) instead of a parallel implementation.
- **Decided (Phase 2):** `UserRepository.get_or_create(user_id)`
  auto-provisions a minimal `User` row (a `sha256(user_id)` placeholder
  `email_hash`) when one doesn't exist. `LearnerProfile.user_id` FK-
  references `users.user_id`, and the session boundary's dev-mode fallback
  (`app/api/deps.py`) has no real signup flow behind it — this was a real
  bug caught by testing against real Postgres (SQLite, the test dialect,
  doesn't enforce FKs by default) — see IMPLEMENTATION_STATE.md "Completed
  Work". A real auth flow should eventually create `User` rows directly;
  `get_or_create` stays safe to keep even then (idempotent).
- **Addition (Phase 6):** `CatalogRepository.get_resources_targeting_skill`
  (a plain `Resource`/`ResourceSkill` join, dialect-portable — unlike
  `search_resources_by_text`/`search_resources_by_vector` above) and
  `update_link_statuses` (bulk `link_status`/`last_verified_at` write for
  the link-validation job, design §15.2). See §15 below.
- **Addition (Phase 5):** `WeeklyPlan`, `PlanRevision`, `PlanItem` (migration
  `0004_planner`) match design §28's table list, with one addition:
  `PlanItem.practice_item_ids` (JSON list) instead of design's single
  `practice_ref?` — no `PracticeSet` generation service exists yet (design
  §18, Assessor, Phase 7 in this project's numbering), so this stores the
  underlying curated `PracticeItem` IDs directly. See §16 below.
- **Addition (Phase 8):** `Assessment`, `StruggleSignal`,
  `LearnerMisconception` (migration `0005_assessment`) match design §28's
  table list, `LearnerMisconception.remediation_cycles` a small field-list
  addition (design §20.8's two-cycle cap needs somewhere to count them).
  `PracticeSession` is a new staging table beyond §28's list entirely — see
  §17 below for the full reasoning (same shape as Phase 2's `PendingClaim`).

## 10. Validation rules (Plan Validator V1–V10)

Hard rules (must be 0% violations on any **committed** plan): V1 time budget, V2
referential integrity, V3 prerequisite order, V4 difficulty band (`difficulty ≤
current_level + 1`), V5 new-skill concurrency cap, V9 post-overload headroom.

Soft rules (checked, logged, but do not block commit): V6 session chunking (≤ 60 min
contiguous), V7 practice pairing, V8 struggle follow-up, V10 guidance fading.

A **Fallback Planner** must always exist and must always satisfy the hard rules
(ignoring soft rules if necessary) — a demo/run can never fail to produce a plan.

**Implemented (Phase 5):** `backend/app/planning/validator.py`'s
`validate_plan()` (V1-V10, plus `V_no_unjustified_duplicates` and
`V_required_objective_coverage` — additive checks from the phase brief, not
literally named in design §17.2, folded in as soft where a genuinely
impossible candidate set could otherwise make 100% coverage unreachable) and
`backend/app/planning/fallback.py`'s `build_fallback_plan()` (design §16.4).
See §16 below for the full set of Phase 5 decisions.

## 11. Error / failure conventions

- LLM schema-validation failure → retry with error feedback, max 2×, then fall
  through to the deterministic path (fallback planner, deterministic classifier,
  etc.) and mark the run `degraded=true` in the trace. Never fail silently, never
  loop unbounded.
- Provider timeout/5xx → exponential backoff (max 2×) → replay cache if a recorded
  response exists → degraded path.
- `RunState.status` is one of `running | needs_user | completed | degraded | failed`.
- Every skipped/degraded step must be visible in the trace (`AgentStep`), not just
  logged server-side.

## 12. Naming conventions

- Status enums are UPPER_SNAKE where they represent skill/plan states (`MET`,
  `WEAK`, `UNVERIFIED`, `MISSING`, `BLOCKED`) and lower_snake for internal field/enum
  values elsewhere (e.g., `status: open | closed`) — follow whatever casing the
  design doc uses verbatim for a given field; do not re-case it during
  implementation.
- Graph edge types are UPPER_SNAKE verbs (`PREREQUISITE_OF`, `REQUIRES`, `TARGETS`).
- Service/module package names mirror agent/service responsibility, one package per
  responsibility (design §35): `profiling/`, `graph/`, `gap/`, `planning/`,
  `assessment/`, `reflection/`, `tutor/`, `provenance/`, `gateway/`. Additions
  beyond this list, same package-per-responsibility convention: `catalog/`
  (Phase 3), `retrieval/` (Phase 6).
- Decision/record types are suffixed `Record` (`DecisionRecord`, `ReflectionRecord`)
  or `Revision`/`Result` per the schema list in §25.2 — reuse the exact schema names
  from that section rather than inventing synonyms.

## 13. Security boundaries (do not weaken without discussion)

- Uploaded documents are **data, never instructions** — no side-effect tools are
  ever exposed to the Profiler; output is schema-only; verbatim-span verification is
  mandatory before any extracted claim becomes evidence.
- Tools with side effects (`commit_*`) are callable **only** by orchestrator commit
  nodes — never exposed to any LLM agent.
- `learner_id` is session-derived everywhere; no query path accepts it from an LLM
  argument or unauthenticated input.
- Web fallback content is allowlisted, SSRF-safe, and always flagged `unvetted` —
  never auto-committed as evidence or a resource. **Implemented (Phase 6):**
  `backend/app/gateway/web_fallback_gateway.py` degrades to `fetched=False`
  (no results) whenever no provider is configured — this project's permanent
  state, since no real web-search provider/domain allowlist has been wired
  in. `WebFallbackResult` deliberately carries no `resource_id` (nothing in
  the catalog to reference), so it can never be confused with a real
  `ResourceRecommendation`.
- MCP is **not** the system backbone (design §26.1). Only a stretch, read-only MCP
  adapter is in scope, and only over already-existing read-only tools.

## 14. Evaluation / demo determinism

- A **record/replay LLM Gateway** cache exists so the full stack can run offline for
  a demo. This is a first-class requirement, not an afterthought — do not build an
  LLM Gateway without it. **Implemented (Phase 12):** durable `llm_replay_entries`
  table + `DbReplayCache`; resolution order, flags and failure behavior in §22.
- Numeric thresholds (mastery cut-offs, load caps, ranking weights) are **tunable
  defaults to be calibrated on the evaluation set** — never hardcode them as if they
  were derived constants, and keep them in one place (config/thresholds), not
  scattered through code.

## 15. Resource retrieval conventions (Phase 6, design §14.3/§15)

- **Package:** `backend/app/retrieval/` — an addition beyond design §35's
  named-package list, same latitude Phase 3 used for `catalog/`.
  `ranker.py` is the pure, deterministic pipeline (no DB/gateway import);
  `service.py` is the async DB-fetch + embedding-call orchestration layer,
  same split as `app/gap/engine.py` (pure) vs. `app/profiling/onboarding.py`
  (orchestration).
- **No resource is ever invented.** Every `ResourceRecommendation.resource_id`
  is drawn from the `candidates` list handed to `recommend()`, which is
  itself sourced from `CatalogRepository.get_resources_targeting_skill` —
  real `Resource` rows via real `TARGETS` edges. There is no code path from
  an LLM output to a `resource_id` or a raw URL in this package.
- **Decided:** hybrid dense+keyword retrieval is computed **in pure Python**
  over already-fetched `Resource` rows (cosine similarity against the
  existing `EmbeddingGateway`-computed `embedding` vector; token-overlap
  keyword scoring), **not** via `CatalogRepository.search_resources_by_text`/
  `search_resources_by_vector` (Postgres-only, §9 above). Reason: those two
  methods already raise `NotImplementedError` under SQLite and are
  documented as "not exercised by pytest" (§9's Phase 3 note) — building the
  Ranker on top of them would make its core algorithm just as untestable,
  directly conflicting with this phase's test requirements. The Ranker's
  hybrid step is therefore dialect-portable and fully unit-tested; the
  Postgres-only FTS/pgvector SQL methods remain available for a future
  phase that specifically needs to query across the *whole* catalog rather
  than an already graph-anchored candidate set.
- **Eligibility filter** (design §14.3 point 2) checks resource `TARGETS`
  the skill (via `get_resources_targeting_skill`, so this is structural, not
  a runtime check), difficulty band overlap
  (`level_from <= current_level + 1 and level_to >= current_level`),
  prerequisites, `link_status == "ok"` (not `"redirected"` — the design
  text's `link_status = ok` is read literally), duration vs. session cap,
  language, and modality exclusion. **Simplification:** "prerequisites are
  MET **or scheduled earlier**" only checks MET — no Planner/schedule exists
  yet to know what counts as "earlier" (Planner is Phase 5, not yet
  implemented as of this phase).
- **MMR diversification** is a strict first-occurrence-per-(provider,
  modality) selection with graceful fallback to duplicates only when the
  eligible pool is too homogeneous to fill `top_k` otherwise — not a
  cosine-based corpus-wide MMR. This matches design §15.3's literal closing
  sentence ("removes near-duplicates — same provider and modality — from
  the top-K"), not the general Maximal Marginal Relevance algorithm by that
  name.
- **Link validation** (design §15.2): `backend/app/retrieval/link_validator.py`
  (HEAD, falling back to GET, `httpx.AsyncClient` injected — same pattern as
  `github_client.py`) is the *live* check; static URL well-formedness is
  already a build-time invariant in `app/graph/validation.py` (Phase 3).
  `backend/scripts/validate_links.py` is the "runs before demo and nightly"
  job entrypoint, writing results via
  `CatalogRepository.update_link_statuses`.
- **No API route this phase.** Design §27's endpoint table has no row for
  the Resource Retriever/Ranker — it is Planner-internal (§14.3: "objective
  → ... → `ResourceRecommendation[]`", consumed by `POST
  /api/learners/me/plans`). Matching that, this phase adds no new HTTP
  surface; `ResourceRetrievalService` is ready for the Planner (Phase 5,
  not yet implemented) to call once it exists.
- **No `LearningActivity` table yet.** design §15.3's `novelty`/
  `penalty_if_prior_failure` components take a `learner_history:
  list[ResourceUsageRecord]` parameter rather than querying a live table —
  no `LearningActivity`/`Assessment` table exists yet to source this from
  (Phase 7/8). The algorithm is complete and tested now; a real caller
  supplies real history once one of those phases writes it.

## 16. Planning conventions (Phase 5, design §16-§17)

- **Package:** `backend/app/planning/` — already named in §12's convention
  list. `candidates.py` (async orchestration: Gap Engine `LearningObjective[]`
  plus Resource Retriever/Ranker output, assembled per objective into an
  `ObjectiveCandidateSet`), `prompting.py` (Planner Agent prompt/parse),
  `validator.py` (pure — V1-V10 plus two additive checks), `fallback.py`
  (pure — the always-valid Fallback Planner), `service.py` (async
  orchestration: builds services, runs the G2 graph, persists
  `WeeklyPlan`/`PlanRevision`/`PlanItem`). Same pure/impure split
  `app/gap/engine.py` and `app/retrieval/ranker.py` already established.
- **G2 Planning graph** (`backend/app/orchestration/graphs.py`'s
  `build_planning_graph`): `build_objectives (Gap Engine) -> retrieve_candidates
  (Retriever/Ranker) -> plan_draft (Planner) -> validate_plan (Validator) ->
  [loop to plan_draft, attempt <= PLANNER_MAX_DRAFT_ATTEMPTS (2)] ->
  fallback_plan`. **Does not include design's `critique` node** (Reflection
  mode a, plan critique) — Reflection is Phase 8, not implemented. The graph
  ends with a finalized in-memory item list; the actual `commit_plan`
  Postgres write happens outside the graph (`app/planning/service.py`), the
  same split Phase 2's `PendingClaim` write already uses (no
  Postgres-backed LangGraph checkpointer exists to hold in-flight state
  across a DB-writing node — see §9's Phase 2 entry).
- **Two Planner Agent modes** (design §8.2): `"draft"` (`create_plan`) and
  `"patch"` (`patch_existing_plan`, design §16/§20). Patch mode is built as a
  **capability** this phase, for Reflection (Phase 8) to call later — this
  phase does not itself decide *when* a patch is warranted, only provides
  the mechanism (same "mechanism now, policy later" split Phase 4 used for
  `LearningObjective` generation ahead of a Planner to consume it).
- **Decided: candidate-ID-only enforcement happens at parse time, not just
  at validation time.** `app/planning/prompting.py`'s `parse_planner_response`
  rejects any resource_id/practice_item_id/objective_id not present in the
  candidate set as a parse error (same retry-then-degrade path as malformed
  JSON) — this section's own "an LLM never emits a raw URL or invents an ID"
  (§7) is enforced before a draft ever reaches the deterministic Plan
  Validator, not only there.
- **Decided: the Planner Agent does not embed its own fallback.** Unlike the
  Profiler Agent (which owns a `DeterministicClaimExtractor` fallback
  internally), `PlannerAgent.run()` returns `degraded=True` with an empty
  item list when the gateway is unavailable or retries are exhausted; the
  **G2 graph**, not the agent, routes to the separate `fallback_plan` node.
  This matches design §9.4's table listing `plan_draft` and `fallback_plan`
  as distinct nodes.
- **`practice_item_ids` instead of `practice_set_id`:** no `PracticeSet`
  generation service exists yet (design §18, Assessor — Phase 7 in this
  project's numbering), so `PlanItem` stores the underlying curated
  `PracticeItem` IDs directly (`app/db/models.py`'s
  `PlanItem.practice_item_ids`, `app/schemas/common.py`'s
  `PlanItem.practice_item_ids`) rather than referencing a set this project
  cannot yet build.
- **Additive validator rules** (`V_no_unjustified_duplicates`,
  `V_required_objective_coverage`): from the Phase 5 brief's "no duplicated
  work without justification" / "required objective coverage", not literally
  named in design §17.2. The duplicate check is **hard** (no two items share
  the same `(skill_id, resource_id)` pair unless `type == "review"`); the
  coverage check is **soft** — a genuinely impossible candidate set (the
  required "impossible candidate set" test case) can make 100% objective
  coverage unreachable for *any* planner, LLM or fallback, and blocking
  commit on it would violate this section's "a demo/run can never fail to
  produce a plan."
- **V8 (struggle follow-up) and V9 (post-overload headroom) accept
  caller-supplied signals rather than querying live data:**
  `effective_budget_minutes`/`effective_new_skill_cap`
  (`app/planning/validator.py`) accept an `overload_active` flag, same
  "mechanism now, real source later" pattern `app/retrieval/ranker.py` used
  for `learner_history` ahead of a `LearningActivity` table. **The Struggle
  Classifier itself is now implemented (Phase 8, see §17 below)** and does
  persist real `cognitive_overload`/struggle signals — but nothing yet
  reads them back into a `create_plan`/`patch_existing_plan` call's
  `overload_active` flag; wiring that hand-off is Reflection's job (design
  §20's re-planning trigger), still out of scope.
- **No API route for `patch_existing_plan`.** Design §27's endpoint table's
  patch/override surface (`POST /api/plans/{id}/override`) belongs to
  Reflection (Phase 8), which decides *when* a patch is warranted. This
  phase exposes only `POST /api/learners/me/plans` and
  `GET /api/learners/me/plans/current` (design §27); `patch_existing_plan`
  is tested directly at the service layer.

## 17. Assessment, Mastery, and Struggle Detection conventions (Phase 8,
design §10.4, §18, §19, §20.8)

- **Package:** `backend/app/assessment/` — already named in §12's
  convention list. `mastery.py` (pure), `struggle.py` (pure), `grading.py`
  (MCQ pure, short-answer async/gateway), `prompting.py` (Assessor Agent
  prompt/parse), `item_bank.py` (async assembly orchestration),
  `resolution.py` (deterministic misconception state machine),
  `service.py` (async orchestration — mirrors `app/planning/service.py`'s
  split).
- **Scope decision (the Phase 8 brief's explicit framing, superseded by
  Phase 9 — see §18 below):** the full Reflection Agent (design §20 —
  LLM-driven root-cause synthesis, a closed operator set, `ReflectionResult`,
  the Reflection Validator, a retry-then-deterministic-patch loop) was
  **not** implemented this phase. `backend/app/assessment/resolution.py`
  implemented only design §20.8's narrower "misconception detected ->
  remediation -> verification probe -> resolved/persistent" loop, with
  exactly one hard-coded trigger (a `repeated_misconception` signal at
  `confirmed` status) rather than an LLM choosing when/how to intervene.
  `INSERT_REMEDIATION` and `ADD_PROBE` were applied directly and
  deterministically via `PlanningRepository` — both already are
  "deterministic function[s] on the plan" per design §20.5's own framing,
  so no LLM round-trip was needed once the trigger fired. **Phase 9 now
  implements the fuller pipeline** (§18); `resolution.py` itself is
  unchanged and its narrower recipe now serves as Reflection's last-resort
  guaranteed-safe fallback rather than the primary path.
- **Mastery is always surfaced as an estimate, never asserted as fact**
  (design §10.4, the Phase 8 brief's explicit instruction):
  `app/assessment/mastery.py`'s `MasteryOutcome` always carries `band` and
  `confidence` alongside the raw `alpha`/`beta`/`estimate` — no code path
  in this package exposes a bare mastery number without them.
- **Decided: the Mastery Updater's tier-upgrade rule deliberately differs
  from `EvidenceCommitService`'s (Phase 2).** `EvidenceCommitService._upsert_skill_state`
  *reseeds* `alpha`/`beta` to a flat prior on a tier upgrade (E0-E2 are
  categorical evidence-strength priors). `update_mastery` instead
  *accumulates* per assessed item on top of whatever `alpha`/`beta` already
  existed (design's explicit `α += w` / `β += w` formula), and any assessed
  item immediately sets `tier_max = "E3"` regardless of the skill's prior
  tier — assessed-in-system evidence is always the strongest tier
  (ARCHITECTURE_CONTRACTS.md §3's ordering).
- **Struggle Classifier is a pure function** (`app/assessment/struggle.py`'s
  `classify_struggle`) over a just-submitted item list plus a
  caller-resolved `StruggleContext` — no DB/gateway import in the module,
  same "unit-testable with hand-built fixtures" shape as `app/gap/engine.py`/
  `app/retrieval/ranker.py`/`app/planning/validator.py`. Multiple classes
  may fire from the same submission; `primary_signal()` applies design
  §19.2's precedence order (misconception > prerequisite gap > difficulty
  mismatch > overload > insufficient practice > low score) only among
  medium/high-confidence signals, matching design §19.3's "low or suspected
  -> schedule_probe, not a routing trigger."
- **Time and retries are corroborating evidence only, never sole
  authority** (design §19.1/§19.5, the Phase 8 brief's explicit
  instruction): no rule in `struggle.py` gates on `ItemOutcome.time_sec`/
  implicit retry count by itself. The only place timing-adjacent context
  matters is `cognitive_overload`'s `>= 2`-corroborating-signals tally,
  where it is one independent signal among several (planned-vs-actual
  ratio, completion rate, self-report, new-skill concurrency) — design's
  literal "time alone is insufficient."
- **Addition:** `PracticeSession`, `Assessment`, `StruggleSignal`,
  `LearnerMisconception` (migration `0005_assessment`) join design §28's
  table list. `PracticeSession` is not itself a design §28 name — it is the
  server-side staging record between assembling a set
  (`POST /api/learners/me/practice`) and grading it
  (`POST /api/practice/{set_id}/submit`), holding answer keys and
  misconception tags **server-side only** (design §18.3), same staging-table
  precedent as `PendingClaim` (Phase 2) and the same reason: no
  Postgres-backed LangGraph checkpointer exists to hold this as in-flight
  `RunState` instead. `LearnerMisconception.remediation_cycles` is an
  addition beyond §28's field list, needed for design §20.8's "after two
  failed remediation cycles -> persistent."
- **Addition:** `CatalogRepository.get_practice_item`/
  `get_practice_items_by_ids`/`create_practice_item`/`get_misconception`/
  `get_misconceptions_for_skill` — the read/write primitives item
  assembly and generated-item storage need; `create_practice_item` writes
  an Assessor-generated item into the **same global item bank** curated
  items live in (design §18.2 point 5's "store in the bank with
  provenance" — `generated_by="assessor-llm"`, `validated_by="blind-solver"`),
  not a separate table.
- **Decided: the Assessor Agent has no offline generation stand-in.**
  Unlike the Profiler (deterministic fallback extractor) or the Planner
  (separate Fallback Planner graph node), there is no rule-based item
  generator — when no LLM provider is configured (this project's default),
  item-bank-first still works fully offline, but generate-if-short simply
  yields nothing (never a fabricated item). Same posture as the VLM
  Gateway's "no offline OCR stand-in" (Phase 2).
- **Decided: invented misconception tags are rejected at parse time, not
  just validated later.** `app/assessment/prompting.py`'s
  `parse_generation_response` rejects any `misconception_id` not in the
  candidate set handed to the LLM as a parse error (retried, then
  degraded) — the same "never invents an ID" enforcement point pattern
  `app/planning/prompting.py` established for resource/objective IDs (§7).
  The **key** option is additionally rejected if it carries a
  misconception tag at all (a wrong-answer-only concept), independent of
  what the candidate set contains.
- **Decided: `grade_mcq` never trusts a client-supplied correctness
  claim** — it always re-derives `correct`/`misconception_id` from the
  stored `PracticeItem.options[chosen_option]`, which the client never
  receives (design §18.3). An out-of-range `chosen_option` index grades as
  incorrect with no misconception tag, never an error.
- **Decided: short-answer grading degrades to `correct=None`
  ("ungraded"), never a guessed pass/fail**, when the gateway has no
  provider configured or returns an unparsable response
  (ARCHITECTURE_CONTRACTS.md §11's graceful-degradation contract, applied
  to grading specifically) — design §18.1's "low-confidence grades
  flagged" is implemented as `confidence="low"` plus `degraded=True`, a
  caller-visible signal to not silently update mastery from it. (This
  project's curated item bank is 100% MCQ, so this path is presently
  exercised only via hand-built fixtures in tests, not real catalog data —
  same situation Phase 6 already documented for a couple of its own
  Postgres-only methods.)
- **Addition: `gap/engine.py`'s `current_level_for`/`mastery_estimate_for`.**
  Public wrappers around the Gap Engine's existing (previously private)
  `_current_level`/`_mastery_estimate` helpers, added so
  `app/assessment/item_bank.py` (level labels for generation prompts) and
  `app/assessment/service.py` (`StruggleContext.current_level`) can reuse
  the exact same tier-gate math instead of re-deriving it.
- **No API route for `record_probe_result` or manual resolution
  transitions.** A resolution-check probe's outcome is inferred
  automatically inside `submit_practice_set` whenever the submitted
  `PracticeSession.purpose == "resolution-check"` — there is no separate
  endpoint a caller invokes to "mark a misconception resolved."

## 18. Reflection & Re-planning conventions (Phase 9, design §20, §21)

- **Package:** `backend/app/reflection/` — an addition beyond §12's naming
  list, same latitude `catalog/`/`retrieval/`/`gap/` already used.
  `operators.py` (pure), `evidence.py` (pure assembly), `deterministic.py`
  (pure root-cause + operator policy), `draft.py` (the shared
  `ReflectionDraft` shape), `prompting.py` (Reflection Agent prompt/parse),
  `validator.py` (deterministic Reflection Validator), `service.py` (async
  orchestration — mirrors `app/assessment/service.py`'s split).
- **Closed operator set is this project's own, not design §20.5's
  verbatim list.** The Phase 9 brief specifies exactly six operators —
  `INSERT_REMEDIATION`, `DEFER`, `REMOVE_DUPLICATE`, `REPLACE_RESOURCE`,
  `ADD_PROBE`, `SPLIT_ACTIVITY` — used here instead of design §20.5's seven
  (`SWAP_RESOURCE`/`ADD_PRACTICE`/`REDUCE_LOAD`/`REORDER`). `REPLACE_RESOURCE`
  ≈ `SWAP_RESOURCE`; `REMOVE_DUPLICATE`/`SPLIT_ACTIVITY` have no design
  §20.5 equivalent (they cover the Plan Validator's own V_DUP/V6 concerns);
  `ADD_PRACTICE`/`REDUCE_LOAD`/`REORDER` are not implemented — `DEFER` and
  `SPLIT_ACTIVITY` cover their load-reduction/chunking intent in this
  project. `apply_operators()` (`app/reflection/operators.py`) is the single
  place every operator's semantics live, deliberately a pure function (no
  DB/gateway import) re-validated by the existing Plan Validator.
- **Root-cause identification is deterministic, never delegated to the
  LLM.** `app/reflection/deterministic.py::deterministic_root_cause` reads
  it straight off the struggle signal (a `missing_prerequisite` signal's
  named prerequisite) or the curated graph (a confirmed misconception's
  `ROOTED_IN` skill via `SkillGraphService`) — consistent with §7's "an LLM
  never invents an ID" and design §20.6 point 3's "on conflict the
  classifier wins." The Reflection Agent (when a provider exists) is handed
  this pre-resolved root cause plus pre-resolved candidate resource/probe
  IDs and chooses/refines *operators* and narrative fields only; the
  Reflection Validator still independently re-checks that whatever
  `root_cause_skill_id` comes back really is the struggling skill or one of
  its hard-prerequisite ancestors.
- **Reflection does not route through `patch_existing_plan` (Phase 5).**
  `patch_existing_plan`'s G2-graph patch mode recomputes objectives/candidates
  fresh and, when the LLM is unavailable (this project's permanent state),
  falls through to `fallback_plan`, which **regenerates a plan from scratch**
  rather than surgically patching the existing one — incompatible with
  design §20.7's "revisions apply to future items only." Reflection instead
  applies its own `apply_operators()` pipeline directly to the current
  revision's items, the same direct-`PlanningRepository`-write approach
  `app/assessment/resolution.py` (Phase 8) already used, generalized to the
  full closed operator set. `patch_existing_plan` remains unused by any
  caller; it is not removed, only bypassed.
- **Fresh `item_id` on every persisted revision, including carried-forward
  items.** `plan_items.item_id` is a global primary key, not scoped per
  revision (`PlanItem.revision_id` is what scopes an item to "the revision
  it belongs to," per Phase 5's own schema note) — so re-inserting a prior
  item under a new `revision_id` with its *old* `item_id` violates the
  primary key. `app/reflection/service.py::_schema_to_row` never carries
  `item_id` forward, matching `app/assessment/resolution.py`'s
  `_apply_remediation_to_plan`, which already did this for the same reason.
- **Layered fallback, never a half-applied plan (design §20.7).** Order:
  (1) the Reflection Agent, retried up to `REFLECTION_MAX_ROUNDS` (2) with
  the Validator's rejection reasons fed back; (2) on agent
  degrade/exhaustion, the deterministic root-cause+operator policy; (3) on
  *that* failing hard validation (defensive — the deterministic policy is
  expected to already produce a valid patch), a last-resort minimal patch
  (`INSERT_REMEDIATION`+`ADD_PROBE` only, no `DEFER` — `resolution.py`'s
  original recipe, demoted to this role); (4) if even that fails, the plan
  is left **unchanged** and a `ReflectionRecord(validated=False,
  ...)`/`needs_attention=True` records the attempt. No partial application
  at any stage — `apply_operators()` either fully succeeds or the caller
  discards its result and tries the next rung.
- **Trigger set generalized beyond Phase 8's single hard-coded trigger.**
  `app/reflection/service.py::pick_trigger` triggers on any of design
  §20.2's four classes (`repeated_misconception`-confirmed,
  `missing_prerequisite`, `excessive_difficulty`, `cognitive_overload`, at
  the Struggle Classifier's own medium/high-confidence + action-precedence
  rules) rather than only a confirmed misconception.
- **Addition:** `ReflectionRecord`, `DecisionRecord` (migration
  `0006_reflection`) join design §28's table list, with real field lists
  from day one (§28's own shapes, not `{id fields..., data: dict}`
  placeholders).
- **Addition:** `PlanningRepository.mark_reverted`,
  `ReflectionRepository` (new), `AssessmentRepository.all_assessment_item_ids_for_learner`.
- **One-click Revert is new HTTP surface** (design §20.7):
  `POST /api/learners/me/plans/{plan_id}/revisions/{revision_id}/revert` —
  only the plan's *current* revision may be reverted (reverting a
  superseded one would silently discard whatever came after it); it creates
  a new revision restoring its parent's content and sets the reverted
  revision's `PlanRevision.reverted_by`.
- **G3 Evidence-Response is still not a LangGraph** — see §17's existing
  framing; `app/reflection/service.py::run_reflection` plays the role
  design's `reflect -> validate_reflection -> [retry] -> patch -> commit`
  nodes would have, as plain async orchestration for the same reason Phase
  8 already gave (interleaved DB writes/reads, no Postgres-backed LangGraph
  checkpointer).

## 19. Tutor & Provenance conventions (Phase 10, design §8.2, §9.6, §14.5,
§23, §24)

- **Packages:** `backend/app/tutor/` and `backend/app/provenance/` — both
  already named in §12's convention list (design §35). `tutor/context.py`
  (the shared per-turn `TutorContext`), `tools.py` (the nine-tool read-only
  inventory), `intent.py` (pure `classify_intent`/`plan_tools`),
  `prompting.py`/`draft.py` (the Tutor Agent's prompt/parse),
  `conservative.py` (the deterministic fallback answer), `report_builder.py`
  (the deterministic Report Builder — pure `build_progress_report` plus an
  async `compute_progress_report` wrapper, the same pure/impure split
  `app/gap/engine.py`/`app/retrieval/ranker.py`/`app/planning/validator.py`
  already established), `service.py` (async orchestration: builds
  `TutorContext`, compiles and runs G4). `provenance/citations.py`:
  `verify_citations` — the Provenance Service's citation-existence check,
  pure, no LLM/DB import.
- **G4 Tutor is a real, bounded LangGraph**
  (`app/orchestration/graphs.py::build_tutor_graph`), unlike G3. G3's plain
  async orchestration was forced by interleaved DB *writes* the next step's
  read depends on (§17/§18's existing framing) — G4 has no writes at all
  (every tool call and the agent call are pure reads), so that reason does
  not apply here, and the graph is a real `StateGraph`:
  `classify_intent -> plan_tools -> [refuse | call_tools -> compose_answer
  -> verify_citations -> [regenerate once, then conservative_answer] ->
  finalize]`.
- **`classify_intent`/`plan_tools` are rule-based, not LLM-driven** — design
  §9.6 explicitly allows either ("small model or rule-based"). This project
  picks rule-based so the phase brief's "maximum tool steps must be bounded"
  holds *by construction*: a fixed, deterministic tool plan (every branch of
  `app/tutor/intent.py::plan_tools` names at most 2 tools, well under
  `TUTOR_MAX_TOOL_STEPS = 4`) can never spiral into an open-ended
  LLM-driven tool-calling loop. Skill-mention extraction
  (`_find_mentioned_skill_id`) is a word-boundary, catalog-anchored
  literal scan — the same approach `app/profiling/claim_extraction.py`'s
  `DeterministicClaimExtractor` (Phase 2) already uses, for the same
  reason: no LLM needed, and a matched `skill_id` is always a real one
  (§7).
- **Citation verification is a separate step from the agent's own
  schema-validation retry**, deliberately. `app/tutor/prompting.py`'s
  parser only rejects malformed JSON (the same retry-then-degrade policy
  every other agent's parser uses, §6/§11) — it does *not* check whether a
  citation actually exists in the given context blocks. That check is
  `app/provenance/citations.py::verify_citations`, called by the G4 graph's
  own `verify_citations` node, with its own distinct failure behavior
  (design §9.6): if it fails, `compose_answer` is retried exactly once with
  the invalid IDs fed back (`TUTOR_MAX_COMPOSE_ATTEMPTS = 2` total
  attempts); if it fails again, or the gateway was degraded from the
  start, the graph falls through to `conservative_answer` — never a third
  LLM call, and never an answer whose citations were not actually checked.
- **The conservative answer is not a summary of the LLM's answer** — it is
  built directly from the same `ToolCallResult.data` the LLM was given
  (`app/tutor/conservative.py::build_conservative_answer`), narrating
  nothing. Its citations are exactly the `citable_ids` of whichever tool
  calls returned usable data, so it is grounded by construction and can
  never fail its own verification. This is also the path
  `LLM_PROVIDER=none` (this project's permanent default) actually exercises
  end to end — every other agent's test file makes the same point about its
  own always-live fallback.
- **The Tutor never proposes or applies a plan override this phase.**
  Design §23.3's "it can offer an override... which becomes an explicit API
  call after the user confirms" is not implemented — the Tutor here is
  read-only in the stronger sense of "cannot even draft an override," not
  just "cannot commit one." `app/reflection/operators.py`'s
  `apply_operators()` pipeline remains the only way a plan actually changes
  (§18). Revisit if a later phase wants the Tutor to draft
  `POST /api/plans/{id}/override` requests for user confirmation.
- **`POST /api/learners/me/chat` is a plain JSON request/response, not
  design §27's SSE stream.** The phase brief asks for the grounded answer +
  citation verification + conservative fallback, not a streaming transport;
  `app/sse/trace.py`'s existing `TraceBus` is available for a later phase to
  wire token-by-token streaming onto once a UI needs it. The response body
  is the same complete, citation-verified answer a stream would have ended
  with.
- **`GET /api/learners/me/progress` narration reuses the Tutor Agent**
  (`app/tutor/service.py::narrate_progress`) rather than a separate
  narration agent (design's own "no separate Summary Agent — folded into
  Tutor" decision) — it collapses the G4 graph's
  `compose_answer -> verify_citations -> [regenerate once] -> conservative`
  ladder down to its essentials, since there is exactly one tool result
  (the report itself) rather than a rule-based tool plan to run first.
- **Addition:** `ReflectionRepository.get_decision_record(learner_id,
  decision_id)` (learner-scoped `DecisionRecord` lookup) — backs both the
  Tutor's `get_decision` tool and the new `GET /api/decisions/{id}` route.
  No new tables this phase — the Tutor reads exclusively from tables every
  earlier phase already owns (`LearnerSkillState`/`Evidence`/`WeeklyPlan`/
  `PlanRevision`/`PlanItem`/`StruggleSignal`/`LearnerMisconception`/
  `DecisionRecord`).

## 20. Frontend read-model API and live trace (Phase 11)

- **Additive, read-only endpoints for the UI** (`backend/app/api/v1/views.py`,
  `backend/app/schemas/views.py`; no decision logic, all learner routes session-derived, §7):
  `GET /api/roles`, `GET /api/catalog/skills?ids=`, `GET /api/catalog/resources?ids=`,
  `GET /api/learners/me/profile`, `GET /api/learners/me/evidence` (span, tier, document
  file name — never a server path), `GET /api/learners/me/skills/{skill_id}` (gap, mastery,
  role requirement, evidence, prerequisites/dependents, resources, misconceptions, plan
  items), `GET /api/learners/me/plans/current/revisions`,
  `GET /api/learners/me/plans/{plan_id}/revisions/{revision_id}` (with items).
- **One write:** `PATCH /api/learners/me/plans/items/{item_id}` sets `planned|done|skipped`
  on an item of the *current* revision only. Superseded revisions are history.
- `ReflectionOut` gained `decision_id` and `reflection_id` (additive).
- **Plan-item ids are fresh per revision (§18).** Clients must not diff revisions by
  `item_id` or by `diff.inserted`; the UI compares by `(type, skill_id, resource_id)`.
- **Live trace is real.** `TraceBus` keeps a bounded replay buffer per run; a request may
  carry `X-Run-Id` (8–64 alphanumerics/hyphens), handled by `TraceRunMiddleware`, which sets
  the `current_run_id` context var; services call `app.sse.trace.emit(actor, kind, summary)`
  (no-op without a run id, never raises). Emit points: profiling (Profiler, Evidence
  Verifier, Skill Normalizer), planning (Gap Engine, Planner, Plan Validator), assessment
  (Assessor, Struggle Classifier), reflection (Reflection Agent, Planner, Plan Validator).
  Summaries are computed from real results; nothing is scripted.
- Bug fixed: `GET /api/learners/me/progress` 500'd once a misconception existed
  (`LearnerMisconception` has no `skill_id`); it now resolves the skill from the catalog.
- Known: unhandled 500s are returned by Starlette's outermost handler without CORS headers,
  so browsers surface them as network failures. The UI's unreachable/5xx copy covers both.

## 21. Frontend contracts (Phase 11)

Full design rules: `docs/FRONTEND_DESIGN_SYSTEM.md`.

- **Stack:** Next.js 16 App Router, React 19, Tailwind v4, shadcn/ui (base-nova, Base UI),
  Motion (`import { motion } from "motion/react"`), lucide icons, Playwright + axe for checks.
  No other animation, state or chart library. `cn` lives in `lib/utils.ts` (clsx + tailwind-merge).
- **Design tokens:** CSS variables in `app/globals.css` (`--sheet/--paper/--plate/--ink*/--rule*/
  --verified/--revision`), exposed as Tailwind colors (`bg-paper`, `text-ink-2`, `border-rule-strong`).
  shadcn variables are bound to them. Components must not hard-code hex values.
- **Location & naming:** domain components `components/edupath/<kebab>.tsx`, exported PascalCase;
  shadcn primitives `components/ui/`; routes under `app/dashboard/*` (authenticated learner app),
  `/start` (onboarding), `/` (entry). API access only through `lib/api-client.ts`; types mirror
  backend schemas in `lib/types.ts`.
- **API state handling:** every read uses `useQuery(key, fetcher)` (`lib/query.ts`): status
  `loading | ready | error`, shared cache, `invalidate(prefix)` after mutations. A 404 from a
  "current X" endpoint is data (`null`), not an error. Each surface renders `LoadingState`,
  `EmptyState`, `ErrorState` and `DegradedNotice` explicitly; no bare text states.
- **Tracing:** wrap backend calls that should stream with `traced(label, runId => api.x(..., runId))`
  (`lib/trace-store.ts`). Never fabricate events.
- **Demo mode:** `NEXT_PUBLIC_DEMO_MODE=true` only. Demo assets are in `public/demo/` and are
  submitted through real endpoints. Off by default; `.env*` is git-ignored.
- **Animation:** Motion only; `MotionConfig reducedMotion="user"` at the root; every animation
  communicates state; the revision cloud is the one authored moment.
- **Accessibility:** WCAG 2.2 AA; enforced by `e2e/smoke.spec.ts` (axe serious/critical = 0).
- **Breakpoints:** 375 / 768 / 1024 / 1440; rail at ≥1024, bottom tabs below; no horizontal
  page scroll.
- **Performance:** heavy visualisation (`SkillGraph`) via `next/dynamic`; pages are client
  components only where data is per-learner; the landing page is a server component.

## 22. Observability, record/replay, demo mode and deployment (Phase 12)

- **LLM Gateway never raises into an agent.** `LLMGateway.complete` resolves in this order and
  returns an `LLMResponse` in every case: (1) `REPLAY_MODE=true` → the recorded response for the
  prompt hash; (2) `LLM_PROVIDER != none` → live call (timeout `LLM_TIMEOUT_S`, backoff, at most
  1 + 2 attempts); a successful non-degraded answer is *recorded* when `LLM_RECORD=true` or
  `DEMO_MODE=true`; (3) live failed / no provider → the recorded response, if any; (4) degrade
  (`degraded=True`) → the caller's deterministic path. A degraded stub is never recorded or replayed.
  `LLMResponse` gained `tokens_in/out`, `model`, `latency_ms`, `error`. The one implemented provider is
  `anthropic` (`app/gateway/providers.py`, plain `httpx`); an unknown provider degrades, it does not
  crash. The embedding / VLM / web-fallback gateways always use their deterministic implementation (no
  provider exists for them) — a configured `LLM_PROVIDER` must never make them raise.
- **Every `/api` request except `/api/health` and the SSE stream is a run.** `TraceRunMiddleware` opens
  a `RunContext` (`app/observability/context.py`), honors a valid client `X-Run-Id` (8–64
  alphanumerics/hyphens) or generates a UUID, echoes it as the `X-Run-Id` response header, and persists
  `AgentRun` + `AgentStep` rows after the response (`app/observability/store.py`; never fails the
  request; state-changing requests and any request that produced steps are persisted, bare GETs are
  not). `learner_id`/`user_id` are bound by the auth dependencies. Persisted per step: actor, kind,
  summary, refs, `input_ref`/`output_ref` (IDs, never payloads), `decision_id`, `duration_ms`,
  `tokens_in/out`, `cost_usd`, `status` (`ok | degraded | error`). Per run: route, graph, HTTP status,
  duration, LLM calls / retries / replays / degraded calls, tokens, cost, planner loops, retrieval time,
  `status` (`completed | degraded | failed`). Steps come from `app.sse.trace.emit` / `span`
  (`publish=False` keeps a step in the audit trail without pushing it to the learner-facing SSE panel —
  used for per-LLM-call and per-retrieval bookkeeping). `emit` without a `RunContext` keeps the Phase 11
  behavior (SSE-only when `current_run_id` is set).
- **Read APIs:** `GET /api/runs/{run_id}` (owner only; a foreign or unknown run is 404),
  `GET /api/learners/me/runs`, `GET /api/metrics` (learner-anonymous aggregates: latency p50/p95, LLM
  calls, retries, planner loops, tokens, cost, degraded/failed rates, by graph).
- **Tables (migration `0007_observability`):** `agent_runs`, `agent_steps`, `llm_replay_entries`.
  `agent_runs.user_id/learner_id` are deliberately not FKs (an audit row must survive a missing profile).
- **DEMO_MODE (`DEMO_MODE=true`):** `POST /api/demo/seed` re-creates the persona "Asha"
  (`learner_id = demo-learner-asha`, fixed so replay hashes are stable) for the session user through the
  real services: `apply_intake` → `ingest_file_document` (the demo resume) → claim confirmation → seeded
  evidence state (`demo_learner_state.json`, evidence rows labelled `source_type="demo_seed"`) → week-0
  plan. `POST /api/demo/scripted-attempt` submits the scenario's scripted wrong answers through the real
  `submit_practice_set`; option indexes are resolved server-side (keys never reach a client).
  `GET /api/demo/preflight` (always available) is the design §38.3 rehearsal checklist. Both write
  endpoints answer 403 unless `DEMO_MODE=true`. The seed erases any prior state held by the persona's
  fixed learner id — a single-tenant rehearsal feature, not multi-user safe.
- **Demo data invariants (`data/scripts/validate_dataset.py` enforces):** every scripted answer names a
  real *wrong* option carrying the scripted misconception tag (or a real key); the scenario's expected
  operators are `INSERT_REMEDIATION`, `ADD_PROBE` (`DEFER` is optional — it only fires when the affected
  skill has a scheduled item).
- **Deployment:** the API seeds the catalog on start iff it is empty (`AUTO_SEED_CATALOG`,
  `app/catalog/bootstrap.py`) — never re-ingesting a populated catalog (`replace_all` would violate
  learner-scoped FKs). `DATASET_DIR` overrides the dataset location (Compose mounts `./data` at `/data`).
  `NEXT_PUBLIC_*` are Docker **build args** (Next.js inlines them at build time).
- **Unhandled 500s** carry `Access-Control-Allow-*` for the single configured frontend origin
  (`app/core/errors.py`), so browsers no longer report them as network failures.
- **Test tiers:** `tests/integration` (full journey), `tests/evaluation` (gold sets + independent
  oracles; writes `backend/reports/evaluation_metrics.{json,md}`), `tests/security`, plus
  `test_observability.py`, `test_llm_gateway.py`, `test_demo_mode.py`. `scripts/run_journey.py` drives the
  same `JourneyDriver` against a running stack for smoke + benchmark.

### 22.1 Provider adapters (Phase 12b)

- `LLM_PROVIDER` = `none | groq | huggingface | anthropic`. `groq` / `huggingface` share `call_openai_compatible`
  (`app/gateway/providers.py`): system + user message, `response_format: json_object` (`LLM_JSON_MODE`; one plain-text retry if the
  provider rejects it), `reasoning_effort` only for `gpt-oss` models, usage mapped from `prompt_tokens` / `completion_tokens`. A 429 carries
  `retry_after`; the gateway honors it, bounded at 15 s. Other 4xx (incl. 413) are non-retryable and degrade.
- `EMBEDDING_PROVIDER` = `none | huggingface`. Vectors are truncated to `EMBEDDING_DIM` (256) and re-normalized (Matryoshka), so the schema is
  unchanged. **Catalog and query embeddings must come from the same provider** (`scripts/reembed_catalog.py`). A failed remote call falls back to
  the deterministic embedding, logged, never cached.
- `VLM_PROVIDER` = `none | huggingface`: transcription only; the transcript still passes the Profiler's verbatim-span verification.
- `WEB_SEARCH_PROVIDER` = `none | tavily`: results are https, allowlisted (re-checked in code, not trusted to the provider), title-only,
  `unvetted`; exposed only at `GET /api/learners/me/skills/{skill_id}/web-resources`; never a plan input or a `resource_id`.
- Prompts must carry the constraints their validator enforces (Planner: new-skill cap, unmet prerequisites, max difficulty) and the exact
  allowed citation set (Tutor). Tool output handed to a model is bounded (`MAX_GAPS_SHOWN` etc.).
- Tests never use live providers: `tests/conftest.py` pins every provider to `none` and blanks every key.

