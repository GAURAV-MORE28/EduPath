# EduPath — Changelog

All notable changes to the EduPath project are recorded here, newest first.
This is an engineering changelog (what changed and why it matters for
implementation state), not a marketing changelog.

Format per entry: `## [Phase N | date] Short title` followed by a short bullet list.

---

## [Phase 12 | 2026-09-20] Integration, evaluation and demo hardening

No major features; the system was driven end to end and made reliable. Full status:
`docs/FINAL_IMPLEMENTATION_STATUS.md`. Contracts: `ARCHITECTURE_CONTRACTS.md` section 22.

- **Observability:** `TraceRunMiddleware` gives every `/api` request a run (client `X-Run-Id` or UUID,
  echoed as a response header) persisted as `AgentRun` + `AgentStep` (migration `0007_observability`):
  run/step/learner ids, actor, input/output refs, decision link, duration, tokens/cost, status; counters
  for LLM calls, retries, replays, planner loops, retrieval time. `GET /api/runs/{id}` (owner only),
  `/api/learners/me/runs`, `/api/metrics`. `emit(..., publish=False)` and `span()` added.
- **LLM Gateway:** never raises (replay, live, recorded, then degrade); bounded retries; durable
  `llm_replay_entries` record/replay cache; `anthropic` adapter over `httpx`; tokens/cost per call. The
  embedding/VLM/web-fallback gateways no longer raise for a configured provider (**a provider other than
  `none` used to turn intake, upload and planning into 500s**).
- **DEMO_MODE:** seeded persona "Asha" (`POST /api/demo/seed`), deterministic scripted struggle
  (`POST /api/demo/scripted-attempt`, keys stay server-side), rehearsal `GET /api/demo/preflight`,
  `scripts/seed_demo.py`, `erase_learner_data`. Dataset fixed at its source: the scenario scripted a
  distractor that did not exist and expected a `DEFER` that cannot fire; the validator now checks scripted
  answers against the bank.
- **Journey driver:** `app/demo/journey.py` + `scripts/run_journey.py` (integration test, smoke test,
  benchmark and rehearsal are one code path). `app/profiling/intake.py` extracted from the learners route.
- **Evaluation** (`backend/tests/evaluation`, writes `backend/reports/evaluation_metrics.*`): evidence
  correctness 1.00; normalization top-1 1.00; gap statuses vs an independent oracle 1.00 over 3,500
  statuses; prerequisite consistency 1.00; retrieval eligibility violations 0 (graph anchoring P@3 1.00 vs
  0.26 vector-only); plan validity 1.00 over 10 personas; struggle 4 classes x 25 simulated learners 1.00 with
  0 false positives on 100 benign; reflection root cause 1.00 (10 misconceptions); citation-existence 1.00
  (465 citations). Honest negatives recorded: 56% retrieval coverage at the 45-minute session cap and 4-38%
  budget utilization.
- **Security** (`backend/tests/security`): injection (documents, intake, chat), 8 invalid-upload classes,
  path traversal, SSRF-style GitHub URLs, learner isolation across every id-bearing route, invalid tool
  calls, unsupported roles, broken resources.
- **Fixes found by hardening:** Tutor `search_resources` omitted `met_skill_ids`; unhandled 500s lacked CORS
  headers; catalog alias gaps (CI/CD, Big-O, Kubernetes, AWS, Terraform, matrices, machine learning,
  REST API); the persona left `chain_rule` BLOCKED; `HTTP_422_UNPROCESSABLE_ENTITY` deprecation.
- **Deployment:** `docker compose up` used to leave the catalog empty (nothing seeded it, `data/` was outside
  the build context). Now: catalog seeded on first start iff empty, `./data` mounted, API healthcheck, `web`
  waits for a healthy API, document volume, `NEXT_PUBLIC_*` as build args. **Not verified end to end** (Docker
  Desktop's engine wedged mid-session); config validates and the equivalent real-`uvicorn` start was verified.
- **Tests:** 466 to 572 (integration, evaluation, security, gateway, observability, demo, tutor regression).

## [Phase 11 | 2026-09-20] Frontend design toolchain and premium adaptive-learning UI

- **Toolchain** (setup): UI/UX Pro Max skill installed to `.claude/skills/ui-ux-pro-max`; shadcn/ui
  initialised (base-nova); Playwright + Chromium + `@axe-core/playwright`; Motion 13 confirmed;
  21st MCP added at local scope (connected; tools load after a restart); Impeccable and
  frontend-design plugins active. `PRODUCT.md` and the direction contract written.
- **Design system** "The Checked Set": `docs/FRONTEND_DESIGN_SYSTEM.md`, tokens in `globals.css`,
  ~30 components in `frontend/components/edupath/`.
- **Screens on real APIs:** landing, onboarding (goal, upload, claim review, first plan), overview,
  evidence ledger, skill map + skill drawer, gaps and objectives, weekly plan, practice, progress,
  tutor, agent trace. Centrepiece: `AdaptiveMoment` (causal chain, before/after, revision clouds,
  evidence citations, revert).
- **Backend (additive):** read-model endpoints (roles, catalog skills/resources, profile, evidence,
  skill detail, revision list/detail), `PATCH` plan-item status, `decision_id`/`reflection_id` on
  `ReflectionOut`, real SSE trace emission with a replay buffer and `X-Run-Id` (ARCHITECTURE_CONTRACTS
  §20). Fixed a 500 on `/progress` when a misconception exists. 466 backend tests pass.
- **Verification:** Playwright suite (56 checks: 4 breakpoints x 11 routes, axe on every route, skip
  link) plus a real-API journey spec (intake to reflection to revert).

## [Phase 10 | 2026-09-20] Tutor, Progress Reports and Provenance

- Added `backend/app/tutor/` (design §8.2, §9.6, §23; ARCHITECTURE_CONTRACTS.md
  §2, new §19 — the fifth and last LLM agent, read-only):
  - `context.py`: `TutorContext` — the per-turn bundle of already-built
    deterministic services (graph, catalog, repos, retrieval service, one
    precomputed `GapAnalysisResult`) every tool call and the agent share.
  - `tools.py`: the nine-tool read-only inventory (`get_learner_state`,
    `get_gaps`, `get_current_plan`, `get_revisions`, `get_evidence`,
    `explain_skill_path`, `search_resources`, `get_progress`,
    `get_decision`) — none can mutate anything, and every `citable_ids`
    entry is copied from a real row/graph node the call just read, never
    invented.
  - `intent.py`: rule-based `classify_intent`/`plan_tools` (design §23.1's
    question-type table) — deterministic by design choice, so "maximum tool
    steps must be bounded" (the phase brief) holds by construction rather
    than by a runtime guard against an LLM-driven tool loop. Skill mentions
    are matched via the same word-boundary catalog scan
    `DeterministicClaimExtractor` (Phase 2) already established.
  - `prompting.py`/`draft.py` + `agents/tutor.py` (real `TutorAgent`,
    replacing the Phase 1 placeholder): `compose_answer`'s prompt/parse —
    strong-tier LLM, JSON `{answer, citations}`, retried on malformed JSON
    up to 2× then degrades. Citation *existence* checking is deliberately
    not this agent's job (see below).
  - `conservative.py`: the deterministic, LLM-free answer built directly
    from tool-call data — always grounded by construction, and what
    `LLM_PROVIDER=none` (this project's permanent default) actually
    exercises end to end.
  - `report_builder.py`: the deterministic **Report Builder** — buckets the
    Gap Engine's own already-computed statuses (`MET` -> acquired, `WEAK`
    -> in progress, everything else -> remaining gaps), plus open struggle
    signals/misconceptions and plan-item completion/next-steps. A pure
    function (`build_progress_report`) plus an async DB-fetch wrapper
    (`compute_progress_report`), same pure/impure split every other phase's
    deterministic core uses. The LLM only narrates its output afterward
    (`service.py::narrate_progress`) — it never computes any of the buckets
    itself (the phase brief's explicit requirement).
  - `service.py`: `run_chat` (builds `TutorContext`, compiles and runs the
    new G4 graph) and `narrate_progress`.
- Added `backend/app/provenance/citations.py`: `verify_citations` — the
  Provenance Service's citation-existence check (design §14.5: "may
  reference only IDs present in their context... every cited ID exists"), a
  pure function over an answer's claimed citations and the pool of IDs this
  turn's tool calls actually surfaced.
- **G4 Tutor** (`backend/app/orchestration/graphs.py::build_tutor_graph`,
  replacing the Phase 1 placeholder) is a real, bounded LangGraph — unlike
  G3, every step here is a read, so there was no interleaved-DB-write reason
  to fall back to plain async orchestration: `classify_intent -> plan_tools
  -> [refuse | call_tools -> compose_answer -> verify_citations ->
  [regenerate once] -> finalize | conservative_answer]`.
- `ReflectionRepository.get_decision_record(learner_id, decision_id)` added
  (learner-scoped lookup — the Tutor's `get_decision` tool and the new
  `GET /api/decisions/{id}` route both use it).
- `ProgressReport` (`app/schemas/common.py`) got its real design §25.2 field
  list this phase (previously `{learner_id, data: dict}`), plus three new
  supporting models (`ProgressSkillEntry`, `StruggleAreaEntry`,
  `ProgressActivityEntry`).
- New endpoints (`backend/app/api/v1/tutor.py`, design §27):
  `POST /api/learners/me/chat` (plain JSON request/response, not the SSE
  stream design describes — see that module's docstring for why),
  `GET /api/learners/me/progress`, `GET /api/decisions/{id}`.
- New thresholds: `TUTOR_MAX_TOOL_STEPS` (4), `TUTOR_MAX_COMPOSE_ATTEMPTS`
  (2 — "regenerated once"), `TUTOR_SEARCH_RESOURCES_TOP_K`,
  `PROGRESS_REPORT_NEXT_STEPS_LIMIT`.
- Tests: 49 new (`test_provenance_citations.py`, `test_report_builder.py`,
  `test_tutor_tools.py`, `test_tutor_intent.py`, `test_tutor_agent.py`,
  `test_tutor_service.py`, `test_tutor_api.py`) — every tool's citable-ID
  set checked against real curated-graph IDs, the conservative-answer path
  (the one `LLM_PROVIDER=none` actually exercises end to end), and the full
  HTTP-layer flow via `app_client`. **455 tests total, all passing.**

## [Phase 9 | 2026-09-20] Reflection & Re-planning

- Added `backend/app/reflection/` (design §20, §21; ARCHITECTURE_CONTRACTS.md
  new §18 — this project's own numbering; design calls this "Phase 8," the
  core differentiator):
  - `operators.py`: the Phase 9 brief's own closed six-operator set —
    `INSERT_REMEDIATION`/`DEFER`/`REMOVE_DUPLICATE`/`REPLACE_RESOURCE`/
    `ADD_PROBE`/`SPLIT_ACTIVITY` — with `apply_operators()`, a **pure
    function** over `PlanItem`s re-validated directly by the existing Plan
    Validator.
  - `evidence.py`: `EvidenceBundle` — pure assembly of the struggle signal,
    misconception linkage, hard-ancestor gap statuses, current plan items,
    and the learner's own evidence-ownership universe.
  - `deterministic.py`: root cause identified deterministically (never by
    an LLM) off the struggle signal or the curated graph's `ROOTED_IN`
    edge, across all four design-§20.2 trigger classes.
  - `agents/reflection.py` (real, replacing the Phase 1 placeholder) +
    `prompting.py`: strong-tier LLM, strict ID-validated JSON parsing,
    retried up to `REFLECTION_MAX_ROUNDS` then degrades.
  - `validator.py`: the deterministic Reflection Validator — root
    cause exists and is self/ancestor; evidence belongs to the learner and
    supports the signal; class agrees with the classifier (classifier wins
    on conflict); operators are closed-set/valid; the patched plan still
    passes the Plan Validator's hard rules.
  - `service.py`: orchestration — cooldown -> agent round loop ->
    deterministic policy -> `resolution.py`'s narrower recipe as a final
    guaranteed-safe fallback -> commit `PlanRevision`+`ReflectionRecord`+
    `DecisionRecord`, or leave the plan unchanged with `needs_attention=True`
    if every rung fails. `app/assessment/resolution.py` itself is
    unchanged. Reflection does **not** route through `patch_existing_plan`
    (Phase 5) — see ARCHITECTURE_CONTRACTS.md §18 for why.
- Migration `0006_reflection`: `ReflectionRecord`, `DecisionRecord`.
- `SubmitPracticeResponse.remediation` (Phase 8's `RemediationOut`) replaced
  by `.reflection` (`ReflectionOut`) — richer: root cause, operators,
  `needs_attention`, `degraded`, `rounds`, explanation.
- New endpoint: `POST /api/learners/me/plans/{plan_id}/revisions/{revision_id}/revert`
  (design §20.7's one-click Revert).
- Tests: 31 new (operators, validator, agent, and the real-curated-dataset
  chain_rule -> backpropagation wow scenario end to end, matching
  `data/dataset/demo/demo_scenario.json`'s `expected_reflection_operators`).
  **406 tests total, all passing.**

## [Phase 8 | 2026-09-20] Assessment, Mastery, and Struggle Detection

- Added `backend/app/assessment/` (design §10.4, §18, §19, §20.8;
  ARCHITECTURE_CONTRACTS.md §2, new §17 — already named in §12's
  package-naming convention list):
  - `mastery.py`: `update_mastery()` — a **pure function** implementing
    design §10.4's Beta-count formula (`α += w` on correct, `β += w` on
    incorrect, difficulty-weighted, reversed for incorrect), accumulating
    on top of any prior evidence-tier state rather than reseeding it
    (deliberately different from `EvidenceCommitService`'s Phase 2 rule —
    see §17). Any assessed item sets `tier_max = "E3"`. Always returns
    `band`/`confidence` alongside the raw numbers — mastery is an
    estimate, never asserted as fact.
  - `struggle.py`: `classify_struggle()` — a **pure function** implementing
    all six design §19.2 classes (`low_score`, `repeated_misconception`,
    `missing_prerequisite`, `excessive_difficulty`, `cognitive_overload`,
    `insufficient_practice`). Multiple classes can fire; `primary_signal()`
    applies design's precedence order among medium/high-confidence signals
    only. Time/retries are corroborating evidence only — no rule gates on
    them alone, only `cognitive_overload`'s `>= 2`-signal tally.
  - `grading.py`: `grade_mcq()` (deterministic, re-derives correctness from
    the stored key server-side, never trusts client input) and
    `grade_short_answer()` (small-tier LLM, rubric-based, degrades to
    `correct=None`/`confidence="low"` rather than a guess).
  - `prompting.py`: Assessor Agent prompt/parse — rejects an invented
    misconception tag at parse time exactly like the Planner rejects an
    invented resource ID; rejects a misconception tag on the key option.
  - `item_bank.py`: `assemble_practice_set()` — item-bank-first (excluding
    previously submitted items), generate-if-short (persists validated
    generated items into the same global `PracticeItem` bank with
    provenance), and the prerequisite-block rule (design §13.4's demo
    chain: >= 2 items on an `UNVERIFIED` hard prerequisite).
  - `resolution.py`: a deterministic misconception resolution state machine
    (suspected/confirmed -> remediating -> resolved/persistent, design
    §20.8) — real `REMEDIATED_BY` resource lookup, a 24h cooldown, and a
    direct `PlanningRepository` insert (`INSERT_REMEDIATION`/`ADD_PROBE`)
    rather than routing through the Planner Agent or the full Reflection
    Agent (out of scope this phase — see §17 for the scope-boundary
    reasoning).
  - `service.py`: `create_practice_session()`/`submit_practice_set()` — the
    design §9.5 G3 Evidence-Response flow scoped to this phase
    (`record_evidence -> grade -> update_mastery -> detect_struggle ->
    route`), implemented as plain async orchestration rather than an
    explicit LangGraph graph (no branching/retry loop the way G2 needs one;
    see IMPLEMENTATION_STATE.md's "Agent Status").
- Implemented the real Assessor Agent (`backend/app/agents/assessor.py`):
  strong-tier item generation (misconception-tagged distractors) retried up
  to 2x on schema/tag failure, then small-tier blind-solver validation per
  item (fails closed on any ambiguity — degraded gateway, unparsable
  response, or a wrong pick are all treated as "drop the item," never
  partially trusted). No offline generation stand-in exists; item-bank-first
  still works fully offline.
- Added Postgres tables (`backend/app/db/models.py`, migration
  `0005_assessment`): `PracticeSession` (addition beyond design §28 — the
  server-side staging record between assembling and submitting a set, same
  shape as Phase 2's `PendingClaim`), `Assessment`, `StruggleSignal`,
  `LearnerMisconception` (design §28, `remediation_cycles` a small field
  addition for design §20.8's two-cycle cap).
- Added API routes (`backend/app/api/v1/practice.py`, design §27):
  `POST /api/learners/me/practice` (`{skill_id, purpose?}`) and
  `POST /api/practice/{set_id}/submit`. Response items never carry
  `is_key`/`misconception_id` (design §18.3); `learner_id` always
  session-derived. No route for manually resolving a misconception — a
  resolution-check submission's outcome is inferred automatically from
  `PracticeSession.purpose`.
- `AssessmentResult`/`StruggleSignal` (`backend/app/schemas/common.py`) got
  their real design §25.2 field lists this phase, plus a new
  `AssessmentItemResult` sub-model. New `backend/app/schemas/assessment.py`
  for the practice-set/submit request/response shapes.
- Small addition to `backend/app/gap/engine.py`: public
  `current_level_for`/`mastery_estimate_for` wrappers around its previously
  private tier-gate helpers, so this phase reuses the exact same math for
  generation-prompt level labels and `StruggleContext.current_level`
  instead of re-deriving it.
- **Decided: the full Reflection Agent (design §20) is out of scope.** The
  Phase 8 brief asked only for "misconception detected -> remediation ->
  verification probe -> resolved/persistent" (design §20.8), not the
  LLM-driven root-cause synthesis, closed operator set, or Reflection
  Validator design §20 as a whole describes. `resolution.py` implements
  exactly that narrower loop, deterministically, with one hard-coded
  trigger. See ARCHITECTURE_CONTRACTS.md §17.
- **Bug found and fixed via real-catalog testing (not a code bug in the
  usual sense — a curated-data quirk):** several `skill.chain_rule` items
  have their correct option also carrying a stray `misconception_id` tag.
  `grade_mcq` already nulls any tag on a correct answer regardless, so no
  behavior changed; flagged for Phase 3's outstanding human review pass.
- **Verified against a real Postgres 16 + pgvector container this
  session:** `alembic downgrade base` + `upgrade head` round-tripped all
  five migrations cleanly; a full intake -> create-practice-set -> submit
  round trip on real `skill.chain_rule` items correctly triggered
  deterministic remediation with real `misc.chain_rule_sum` resources
  (`res.khan_diff_calc`/`res.3b1b_calculus`/`res.cs231n_backprop`) once two
  distinct wrong-tagged items were submitted for a fresh learner. Also
  surfaced (and worked around, not fixed — a real open design question) a
  `CatalogRepository.replace_all()` re-ingestion FK-violation issue once
  real learner-scoped rows exist in the same database — see
  IMPLEMENTATION_STATE.md "Known Issues".
- 89 new backend tests: `tests/test_mastery.py` (15), `tests/test_struggle_classifier.py`
  (35, every one of the six classes individually plus cross-class
  exclusion/precedence — the phase brief's explicit "test every struggle
  class" instruction), `tests/test_grading.py` (8), `tests/test_assessor_agent.py`
  (6, mirroring `test_profiler_agent.py`'s `ScriptedLLMGateway` pattern),
  `tests/test_resolution.py` (14, a small hand-built graph fixture), `tests/test_assessment_integration.py`
  (4, real curated dataset via `catalog_session`), `tests/test_practice_api.py`
  (7, full HTTP-layer flow via `app_client`). **375 tests total, all
  passing** (286 from Phase 1-6, 89 new).
- Updated `docs/ARCHITECTURE_CONTRACTS.md` §2, §3, §6, §9, and a new §17
  covering every Phase 8 decision in full.
- **Not implemented this phase (out of scope, per the phase brief and
  design's phase ordering):** the full Reflection Agent / re-planning loop
  (design §20); Tutor. Also not implemented: `no_open_misconceptions_for(skill)`
  wiring into `LearningObjective.acceptance_criteria` (the table it needs
  now exists, nothing reads it yet); a `LearningActivity` table (overload's
  `planned_vs_actual_ratio`/`completion_rate` stay caller-supplied); the
  `missing_prerequisite` "direct probe from a separate recent assessment"
  evidence path (only same-submission prereq-block items and misconception
  attribution are wired); wiring Struggle Classifier output into the Plan
  Validator's V9 `overload_active` flag (Reflection's job).

---

## [Phase 5 | 2026-09-19] Personalized Learning Planner

- Added `backend/app/planning/` (design §16-§17; ARCHITECTURE_CONTRACTS.md
  §10, new §16 — already named in §12's package-naming convention list):
  - `candidates.py`: `build_candidate_sets()` — async orchestration turning
    the Gap Engine's `LearningObjective[]` (Phase 4) into one
    `ObjectiveCandidateSet` per objective, via the Resource
    Retriever/Ranker (Phase 6, `ResourceRetrievalService.recommend_for_skill`)
    for `"lesson"` objectives and curated `PracticeItem`s (new
    `CatalogRepository.get_practice_items_for_skill(skill_id, purpose=...)`)
    for both. New `CatalogRepository.get_resources_by_ids` re-attaches
    resource metadata the Ranker's own output doesn't carry.
  - `prompting.py`: Planner Agent prompt/parse. `parse_planner_response`
    rejects any resource_id/practice_item_id/objective_id not present in
    the candidate set as a parse error — an invented ID is treated exactly
    like malformed JSON (retry-then-degrade), never silently accepted.
  - `validator.py`: `validate_plan()` — a **pure function** (no DB/gateway
    import) implementing design §17.2's V1-V7, V9, V10, plus two additive
    checks from the phase brief (`V_no_unjustified_duplicates`, hard;
    `V_required_objective_coverage`, soft — deliberately soft, since a
    genuinely impossible candidate set can make full coverage unreachable
    for any planner). V8 has no `StruggleSignal` source yet and is a no-op.
  - `fallback.py`: `build_fallback_plan()` — design §16.4's greedy,
    priority-then-topological-layer walk, pure and templated (no LLM). Its
    own output is re-validated against `validate_plan()` directly in tests
    to prove ARCHITECTURE_CONTRACTS.md §10's "always produces a valid plan"
    contract, not just asserted on item counts.
  - `service.py`: `create_plan()` (draft mode) and `patch_existing_plan()`
    (patch mode, design §16/§20 — a capability for Reflection, Phase 8, to
    call later; this phase does not decide *when* a patch is warranted).
    Both run the G2 graph then persist a new `PlanRevision`/`PlanItem` set.
- Implemented the real Planner Agent (`backend/app/agents/planner.py`):
  two modes (`"draft"`/`"patch"`), LLM proposal retried up to 2x on
  schema/ID-validation failure (ARCHITECTURE_CONTRACTS.md §11). Unlike the
  Profiler Agent, this agent does **not** embed its own fallback — on
  gateway unavailability it returns `degraded=True` with an empty item
  list, and the **G2 graph** (not the agent) routes to the separate
  `fallback_plan` node, matching design §9.4's table.
- Implemented the real G2 Planning LangGraph
  (`backend/app/orchestration/graphs.py`'s `build_planning_graph`,
  replacing the Phase 1 placeholder): `build_objectives (Gap Engine) ->
  retrieve_candidates (Retriever/Ranker) -> plan_draft (Planner) ->
  validate_plan (Validator) -> [loop to plan_draft, attempt <= 2] ->
  fallback_plan`. Deliberately excludes design's `critique` node
  (Reflection mode a, Phase 8, not implemented) and does not write to
  Postgres itself — persistence is `app/planning/service.py`'s job outside
  the graph, mirroring Phase 2's `PendingClaim` hand-off.
- Added Postgres tables (`backend/app/db/models.py`, migration
  `0004_planner`): `WeeklyPlan`, `PlanRevision`, `PlanItem` (design §28),
  with one field-shape addition: `PlanItem.practice_item_ids` (JSON list)
  instead of design's single `practice_ref?` — no `PracticeSet` generation
  service exists yet (Assessor, Phase 7 in this project's numbering).
- Added API routes (`backend/app/api/v1/plans.py`, design §27):
  `POST /api/learners/me/plans` (`{week_index?, dry_run?, hours?}`) and
  `GET /api/learners/me/plans/current`. `learner_id`/`role_id`/
  `weekly_hours`/`preferences` always resolved from the session/profile,
  never from the request body. `patch_existing_plan` is deliberately **not**
  exposed via HTTP this phase — design §27's patch/override surface
  belongs to Reflection (Phase 8), which decides *when* a patch is
  warranted.
- `WeeklyPlan`/`PlanItem` (`backend/app/schemas/common.py`) got their real
  design §25.2 field lists this phase, replacing the Phase 1
  `{id fields..., data: dict}` placeholders; new `PlanItemReason` sub-model
  (design §16.6: reasons are ID-attached deterministically, only `text` is
  LLM-phrased/display-only). New `backend/app/schemas/planning.py` for the
  request-only `CreatePlanRequest`.
- New `backend/app/core/thresholds.py` constants: `WEEKLY_BUDGET_SLACK`,
  `OVERLOAD_BUDGET_FACTOR`/`OVERLOAD_CONCURRENCY_REDUCTION`,
  `NEW_SKILL_CONCURRENCY_CAP`/`_NOVICE`, `SESSION_CHUNK_MAX_MINUTES`,
  `PROBE_ITEM_*`, `PRACTICE_ITEM_*`, `PLANNER_MAX_DRAFT_ATTEMPTS`.
- **Bug found and fixed via the integration test suite** (not caught by the
  hand-built-fixture unit tests, since those never round-trip through a
  real session): `_persist_plan` (`app/planning/service.py`) never passed
  `item_id=item.item_id` when constructing each `PlanItemRow`, so every
  persisted row got a *different* auto-generated UUID than the one the
  API's immediate response carried — `GET .../plans/current` would then
  return item IDs that didn't match what `POST` had just returned. Fixed;
  re-verified against a real Postgres 16 + pgvector container too.
- Verified against a real Postgres 16 + pgvector container this session:
  migration `0004_planner` upgrade/downgrade/re-upgrade all ran clean, and
  a full intake → create-plan → get-current-plan round trip through the
  actual FastAPI app returned a real catalog `resource_id`
  (`res.fcc_command_line`) in a fallback-resolved plan.
- 42 new backend tests: `tests/test_plan_validator.py` (17, hand-built
  fixtures — every hard/soft rule individually, the slack/overload math),
  `tests/test_fallback_planner.py` (8, including re-validating the
  fallback's own output for the "impossible candidate set"/"insufficient
  time"/"new-skill-cap" cases), `tests/test_planner_agent.py` (9, mirroring
  `test_profiler_agent.py`'s `ScriptedLLMGateway` pattern, including an
  invented-resource_id-is-rejected-like-invalid-JSON test and two
  patch-mode tests), `tests/test_planning_integration.py` (2, real curated
  dataset via `catalog_session`: a full Gap-Engine-through-Fallback-Planner
  run, and a real-session `create_plan` -> `patch_existing_plan` round
  trip), `tests/test_plans_api.py` (6, full HTTP-layer flow via
  `app_client`). **286 tests total, all passing** (244 from Phase 1-4/6,
  42 new).
- Updated `docs/ARCHITECTURE_CONTRACTS.md` §2, §6, §9, §10, and a new §16
  covering every Phase 5 decision in full.
- **Not implemented this phase (out of scope, per design's phase
  ordering):** assessment, reflection. Also not implemented:
  `LearningObjective.est_minutes_low/high` wiring (both the Gap Engine and
  Resource Retriever are finally in scope together at the Planner, but
  nothing writes the field back yet); a per-learner misconception status
  table (`no_open_misconceptions_for(skill)` still omitted from acceptance
  criteria); `POST /api/plans/{id}/override`/`/revert`,
  `GET /api/plans/{id}/revisions`; a `LearningActivity` table (so
  `PlanItem.status` is always `"planned"`, never transitioned); V8/V9's
  real data sources (Struggle Classifier, Phase 8/9).

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
