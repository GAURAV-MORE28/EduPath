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
| **Assessor** | generation (strong) / grading & validation (small) | No | ❌ |
| **Reflection** | (a) plan critique, (b) evidence-triggered | No — emits operators only | ❌ |
| **Tutor** | read-only | No — cannot mutate the plan; may only propose an override the user confirms | ❌ |

Everything else (Gap Engine, Skill Normalizer\*, Skill Graph Service, Resource
Retriever/Ranker, Plan Validator, Fallback Planner, Mastery Updater, Struggle
Classifier, Reflection Validator, Report Builder, Provenance Service, Trace Emitter)
is a **deterministic service**. No new LLM agents may be added without updating this
file and justifying the addition against design §8.1's role-by-role table.

\* Skill Normalizer uses a small LLM only for ambiguous-alias disambiguation; it is
not counted among the 5 agents. **Implemented (Phase 2):**
`backend/app/profiling/skill_normalizer.py`. **Resource Retriever/Ranker
implemented (Phase 6):** `backend/app/retrieval/ranker.py`'s `recommend()` —
no LLM call anywhere in the package (see §15 below). **Plan Validator and
Fallback Planner implemented (Phase 5):** `backend/app/planning/validator.py`'s
`validate_plan()` and `backend/app/planning/fallback.py`'s
`build_fallback_plan()` — both pure functions, no LLM call anywhere in either
module (see §16 below).

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
Mastery Updater (Phase 7) to accumulate real assessed `alpha`/`beta`; this is
an intentional consequence of this section's fixed priors combined with
§13.4 being an aspirational full-system illustration, not a Phase 4 defect —
see `docs/IMPLEMENTATION_STATE.md`'s Phase 4 "Architectural Decisions".

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
  single `practice_set_id?` (see §16 below for why).

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
  LLM Gateway without it.
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
  caller-supplied signals rather than querying live data:** no
  `StruggleSignal`/overload-detection source exists yet (Struggle Classifier,
  Phase 8/9) — `effective_budget_minutes`/`effective_new_skill_cap`
  (`app/planning/validator.py`) accept an `overload_active` flag, same
  "mechanism now, real source later" pattern `app/retrieval/ranker.py` used
  for `learner_history` ahead of a `LearningActivity` table.
- **No API route for `patch_existing_plan`.** Design §27's endpoint table's
  patch/override surface (`POST /api/plans/{id}/override`) belongs to
  Reflection (Phase 8), which decides *when* a patch is warranted. This
  phase exposes only `POST /api/learners/me/plans` and
  `GET /api/learners/me/plans/current` (design §27); `patch_existing_plan`
  is tested directly at the service layer.
