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

| Agent | Mode(s) | Can mutate persisted state directly? |
|---|---|---|
| **Profiler** | single | No — emits `ExtractedClaims` only |
| **Planner** | draft / patch | No — writes only via validated commit nodes |
| **Assessor** | generation (strong) / grading & validation (small) | No |
| **Reflection** | (a) plan critique, (b) evidence-triggered | No — emits operators only |
| **Tutor** | read-only | No — cannot mutate the plan; may only propose an override the user confirms |

Everything else (Gap Engine, Skill Normalizer\*, Skill Graph Service, Resource
Retriever/Ranker, Plan Validator, Fallback Planner, Mastery Updater, Struggle
Classifier, Reflection Validator, Report Builder, Provenance Service, Trace Emitter)
is a **deterministic service**. No new LLM agents may be added without updating this
file and justifying the addition against design §8.1's role-by-role table.

\* Skill Normalizer uses a small LLM only for ambiguous-alias disambiguation; it is
not counted among the 5 agents.

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

## 4. Skill-gap statuses

`MET | WEAK | UNVERIFIED | MISSING | BLOCKED`

- `UNVERIFIED` → triggers a **verify-before-teach probe**, not a lesson.
- `BLOCKED` → a *hard* prerequisite is `WEAK`/`MISSING`. An `UNVERIFIED` prerequisite
  does **not** block (it gets probed first).
- Gap analysis is 100% deterministic (Gap Engine). No LLM in the decision path — an
  LLM may only narrate the result afterward.

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
  `ReplanRequest`, `ProgressReport`.

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
- The design doc does not mandate a specific ID string format (UUID vs slug); when
  implementing, pick one (UUID v4 recommended for learner/run-scoped rows, stable
  slugs for curated graph/catalog rows) and record the decision here.

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

## 10. Validation rules (Plan Validator V1–V10)

Hard rules (must be 0% violations on any **committed** plan): V1 time budget, V2
referential integrity, V3 prerequisite order, V4 difficulty band (`difficulty ≤
current_level + 1`), V5 new-skill concurrency cap, V9 post-overload headroom.

Soft rules (checked, logged, but do not block commit): V6 session chunking (≤ 60 min
contiguous), V7 practice pairing, V8 struggle follow-up, V10 guidance fading.

A **Fallback Planner** must always exist and must always satisfy the hard rules
(ignoring soft rules if necessary) — a demo/run can never fail to produce a plan.

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
  `assessment/`, `reflection/`, `tutor/`, `provenance/`, `gateway/`.
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
  never auto-committed as evidence or a resource.
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
