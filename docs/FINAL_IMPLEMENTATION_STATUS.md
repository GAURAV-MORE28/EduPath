# EduPath — Final Implementation Status (Phase 12: integration, evaluation, demo hardening)

> Snapshot at the end of Phase 12. Everything below was measured or run in this phase unless it says
> otherwise. Where something could **not** be verified, it says so. `docs/IMPLEMENTATION_STATE.md` is the
> handoff file; `docs/ARCHITECTURE_CONTRACTS.md` §22 holds the new contracts.

## 1. What EduPath is, in one paragraph

An evidence-backed adaptive learning system. A learner uploads a resume; skills are extracted as
span-verified claims and graded by evidence tier; a curated skill graph turns "what the learner wants to
be" into a prerequisite-ordered gap analysis; a validated weekly plan is built from real catalog resources;
practice items carry catalogued misconceptions; a deterministic classifier decides whether a learner is
*genuinely* struggling; a bounded Reflection Agent finds the root-cause prerequisite and revises the plan
(visibly, undoably); a read-only Tutor explains everything with citations that are verified in code.

## 2. Completed features

| Area | Status | Where |
|---|---|---|
| Learner profiling: intake, PDF/DOCX/text/GitHub, Profiler Agent, PII scrub, injection flags, verbatim-span verification, evidence tiers E0–E3, skill normalization, human confirmation | Done | `backend/app/profiling/`, `agents/profiler.py` |
| Skill graph + catalog (158 skills, 3 roles, 203 edges, 140 resources, 18 misconceptions, 95 items), NetworkX queries, validation, versioning | Done | `data/`, `backend/app/graph/`, `catalog/` |
| Gap Engine: statuses, BLOCKED overlay, prerequisite closure/ordering, verify-before-teach objectives, audit flags | Done | `backend/app/gap/` |
| Resource retrieval: graph-anchored eligibility, hybrid dense+keyword (RRF), ranking, MMR, link validation | Done | `backend/app/retrieval/` |
| Planner Agent + Plan Validator V1–V10 + always-valid Fallback Planner, G2 graph | Done | `planning/`, `agents/planner.py`, `orchestration/` |
| Assessor Agent, MCQ + short-answer grading, Beta-count mastery, six-class Struggle Classifier | Done | `assessment/`, `agents/assessor.py` |
| Reflection Agent, closed operator set, Reflection Validator, deterministic fallback ladder, revision + decision records, one-click revert | Done | `reflection/`, `agents/reflection.py` |
| Tutor Agent (9 read-only tools), G4 graph, citation verification, Report Builder | Done | `tutor/`, `provenance/` |
| Frontend (Next.js 16): every journey screen on real APIs, live SSE trace, Playwright + axe | Done (Phase 11) | `frontend/` |
| **Persisted observability**: run id, step id, learner id, actor, input/output refs, decision link, duration, tokens/cost, status; `GET /api/runs/{id}`, `/api/learners/me/runs`, `/api/metrics` | **New** | `backend/app/observability/`, `api/v1/observability.py` |
| **LLM Gateway hardening**: never raises; live → recorded → degraded; bounded retries; durable `llm_replay_entries`; Anthropic adapter; token/cost accounting | **New** | `backend/app/gateway/` |
| **DEMO_MODE**: seeded persona "Asha", seeded evidence state, deterministic scripted struggle, rehearsal preflight, reset | **New** | `backend/app/demo/`, `api/v1/demo.py`, `scripts/seed_demo.py` |
| **Journey driver + benchmark** (one driver: integration test, smoke test, benchmark, demo rehearsal) | **New** | `backend/app/demo/journey.py`, `scripts/run_journey.py` |
| **Automated evaluation** (gold sets, independent oracles, simulated learners) | **New** | `backend/tests/evaluation/` |
| **Security suite** | **New** | `backend/tests/security/` |
| **Deployment fixes**: catalog seeded on first start, dataset mounted, healthchecks, build args, document volume | **New** | `docker-compose.yml`, `app/catalog/bootstrap.py` |

## 3. Bugs found and fixed by this phase's hardening

These were real defects, found by driving the whole system rather than its parts:

1. **Any `LLM_PROVIDER` other than `none` crashed the app.** The LLM, embedding, VLM and web-fallback gateways raised
   `NotImplementedError`, turning intake, upload and planning into HTTP 500s the moment a provider was configured. The gateway now
   never raises (degrades deterministically) and one provider adapter (`anthropic`) exists.
2. **`docker compose up` produced an API with an empty catalog.** Nothing ever ran the seed script and `data/` was outside the
   build context, so intake answered "role not supported". The API now seeds the catalog on first start (only when empty) from a
   mounted `./data`.
3. **The demo scenario had drifted from the item bank.** It scripted a `misc.chain_rule_sum` distractor on items that carry that tag
   only on the *key* option, so the scripted attempt surfaced a different misconception, and it expected a `DEFER` that can never fire
   for the persona. The scenario is fixed at its source (`build_dataset.py`), `validate_dataset.py` now checks that every scripted
   distractor really exists, and the seeded persona's coursework chain is modelled so `chain_rule` is `UNVERIFIED` (not `BLOCKED`).
4. **Tutor `search_resources` did not pass `met_skill_ids`** to retrieval (the Planner does), so resources with prerequisites were
   always ineligible for it. Fixed and regression-tested. (Most "0 catalog resources" answers that remain come from limitation 1 below.)
5. **Unhandled 500s reached browsers as opaque network errors** (no CORS headers on Starlette's outermost handler). Fixed.
6. **Catalog alias gaps** found by the normalization gold set: "CI/CD", "Big-O", "Kubernetes", "AWS", "Terraform", "matrices",
   "machine learning", "REST API" did not map to their own skills.
7. Starlette `HTTP_422_UNPROCESSABLE_ENTITY` deprecation warning removed.

## 4. Evaluation results (measured; `cd backend && python -m pytest tests/evaluation`)

The suite writes `backend/reports/evaluation_metrics.{json,md}` on every run; this table is copied from one. The evaluation
runs with `LLM_PROVIDER=none` — it measures the **deterministic system**, the part that stays the same when a model is attached.

| Area | Metric | Result | Design target |
|---|---|---|---|
| Evidence | evidence correctness (span supports skill) | **1.00** (49 claims / 10 gold resumes) | ≥ 0.95 |
| Evidence | verbatim-span fidelity (vs the PII-scrubbed text) | **1.00** | 1.00 |
| Evidence | skill precision / recall vs gold | 0.92 / 0.94 | report |
| Evidence | forbidden-skill hits (injected / negated skills) | **0** | 0 |
| Normalization | top-1 accuracy, 40 labelled labels | **1.00** | report |
| Normalization | unrecognisable labels left unmapped (8) | **1.00** | 1.00 |
| Gap | status accuracy vs an *independent* oracle (3,500 statuses, 1,338 BLOCKED; 75 random learners × 3 roles) | **1.00** | 1.00 |
| Gap | prerequisite consistency of ordering layers (1,406 edges) | **1.00** | 1.00 |
| Gap | verify-before-teach typing (1,042 objectives) | **1.00** | 1.00 |
| Prerequisites | hard-prerequisite graph acyclic, no dangling edges (129 edges / 125 skills) | **1.00** | 1.00 |
| Retrieval | precision@3 / recall@3 / MRR / NDCG@3 (119 role skills) | 1.00 / 1.00 / 1.00 / 1.00 | report |
| Retrieval | eligibility-violation rate (unknown / broken / off-skill) | **0** | 0 |
| Retrieval | baseline: vector-only, no graph — precision@3 | 0.26 (graph anchoring: 1.00) | report |
| Retrieval | **coverage at the default 45-minute session cap** | **0.56** (67 / 119 skills) | report — see limitation 1 |
| Plan | final validity over 10 personas (budget, real+healthy resources, prerequisite order, no BLOCKED skill scheduled) | **1.00** | 1.00 |
| Plan | personalization, mean pairwise Jaccard distance | 0.54 | > 0.3 |
| Plan | **budget utilization at 2 / 5 / 10 / 20 h per week** | **38% / 15% / 8% / 4%** | report — see limitation 1 |
| Struggle | primary-cause recall & precision, 4 classes × 25 simulated learners | 1.00 / 1.00 each | high |
| Struggle | false-positive interventions on 100 benign learners | **0** | 0 |
| Struggle | root-cause attribution (injected prerequisite / misconception) | **1.00** (50) | 1.00 |
| Reflection | correct root-cause node rate (10 misconceptions the bank can confirm) | **1.00** | ≥ 0.9 |
| Reflection | revisions valid (graph-connected root, closed operator set, committed, decision recorded) | **1.00** | 1.00 |
| Reflection | false-positive reflection rate (benign submissions) | **0.00** | ≈ 0 |
| Adaptation | signal → reflection → decision → revision → trace step linked; revert restores; cooldown holds | **pass** | — |
| Tutor | citation-existence rate (465 citations / 21 questions incl. adversarial) | **1.00** | 1.00 |
| Tutor | out-of-scope / adversarial questions without a fabricated citation | **1.00** | 1.00 |

Two of these numbers are deliberately *not* flattering, and they are the most important ones — see limitation 1.

### Performance (in-process, SQLite; and over HTTP against a real `uvicorn` on an empty database)

| Measurement | Result | Design §33 |
|---|---|---|
| Latency: resume upload / gap analysis / plan / submit → revision / chat | 56 ms / 44 ms / 102 ms / 91 ms / 65 ms | ≤ 25 s / < 1 s / ≤ 15 s / ≤ 20 s / ≤ 3 s |
| Journey wall time (20 calls) | ~0.8 s in-process; 0.8–1.1 s over HTTP | — |
| LLM calls per journey | 7 (all degrade instantly: `LLM_PROVIDER=none`) | ~10–20 with a live model |
| Agent retries / planner loops (plan run) | 0 / 1 (bounded: ≤ 2 retries, ≤ 3 loops) | ≤ 2 retries |
| Tokens / cost | 0 / $0 (no provider) — recorded per call when one exists | — |
| Retrieval speed | 1.2 ms p50, 1.8 ms p95 per skill; ~20 ms per journey | — |

These are **not** Postgres/Docker numbers and there is **no live-model latency** in them. Reproduce against the real stack with
`python scripts/run_journey.py` (§9).

## 5. Security testing (all pass)

| Threat | Verified |
|---|---|
| Prompt injection in a resume | flagged span dropped and *counted*; injected-only skills never become claims/evidence; a resume never mints E2/E3 |
| Prompt injection via intake free text / chat | no state change (row counts identical before/after); other learners' data and IDs never appear |
| Invalid uploads | empty, non-whitelisted extension, executable disguised as PDF/DOCX/PNG, corrupt PDF, over-size, over-page-cap, double extension, zip that is not a DOCX → clean 422/degrade, never a 500, nothing half-stored |
| Path traversal in a filename | stays under the learner's storage directory |
| SSRF via `github_url` | the only outbound host is `api.github.com`; non-GitHub / `file://` / metadata-IP URLs degrade with **no request made** |
| Learner isolation | a second learner gets 404 on another's revision, revert, plan-item PATCH, practice submit, decision and run; nothing changes; foreign claim ids are ignored; the body can never choose the learner; 401 without a session outside dev |
| Invalid tool calls | unknown/`commit_*`-style tools raise; a smuggled `learner_id` argument and hallucinated ids yield an empty, uncitable result; the tool inventory (9) is read-only |
| Unsupported roles | 422 "role not supported", nothing created (also for empty / SQL-ish / wrong-case ids) |
| Broken resources | never scheduled, recommended or cited; a skill with only broken resources yields no recommendations, not an error |

## 6. Remaining bugs / defects

1. **Span offsets index the PII-scrubbed text**, not the stored raw document (identical when a document has no contact PII;
   measured 0.94 valid against raw over the gold set). The verbatim span itself is always correct. Highlighting in the raw file
   would drift after an email/phone.
2. **Evidence recall drops next to an injected sentence**: claims within ~80 characters of a flagged phrase are dropped and counted
   as `dropped_injection` (safe-fail, surfaced). The detector is pattern-based, so ordinary phrases such as "act as a liaison" can
   trigger it.
3. `DEFER` never fires for the seeded persona (backpropagation is `BLOCKED`, so nothing is scheduled to defer); design §20.8's
   "deferred items reinstated" on resolution is not implemented.
4. `skill.chain_rule` has no `resolution-check` practice item, so the demo's follow-up probe carries zero items.
5. Session ids are unsigned (see limitation 3).

## 7. Known limitations (read these before a live demo)

1. **Plans under-fill large budgets — the top limitation.** Retrieval's hard filter `duration ≤ session cap` (design §14.3) removes
   course-length resources (many are 190–360 min), and nothing splits a long resource into segments (design V6's intent). Result:
   only 56 % of role skills have an eligible lesson at the default 45-min cap and a 20 h/week learner is scheduled ~45 min. Plans
   are always *valid* and never over budget; they are often *thin*. The fix is a planner feature (segment splitting +
   duplicate-rule exemption for segments of one resource) — deliberately not done in a hardening phase.
2. **The system runs in "reduced-intelligence" mode by default** (`LLM_PROVIDER=none`): every agent takes its deterministic path
   (deterministic extractor, fallback planner, rule-based reflection, conservative tutor answers). The Anthropic adapter, record/replay
   and retry behavior are unit-tested with mocked HTTP; **they have not been run against the live API**, and the agents' LLM paths
   have only ever been exercised with fakes. Expect prompt/schema tuning when a key is attached.
3. **Authentication is a placeholder**: the `session` cookie is a bare user id (forgeable). Learner isolation is enforced *given* a
   session; there is no login, signing or CSRF protection. `SESSION_SECRET` is unused. Do not expose this to the internet.
4. **The curated content has had no human review** (`reviewed_by: edupath-phase3-curation`), and resource `link_status` has never been
   verified by a live sweep in these sessions (no network): run `python scripts/validate_links.py` before a demo. The item bank
   covers 23 of 158 skills, and 8 of 18 misconceptions lack the ≥ 2 distinct tagged distractors needed to *confirm* them.
5. **`POST /api/demo/seed` is single-tenant**: the persona has a fixed learner id, and seeding erases whatever holds it.
6. Postgres is exercised manually and through SQL-level checks, not by the automated suite (which runs on SQLite): see §8.
7. Not implemented (unchanged, by design of earlier phases): Reflection plan-critique mode, Tutor-drafted overrides,
   `POST /plans/{id}/override`, skill-dispute endpoint, `DELETE /learners/me`, streamed chat, chat-turn persistence, high-impact-change
   confirmation, code sandbox, live web-search fallback, real VLM/OCR (scanned PDFs always need pasted text).
8. `/api/metrics` is unauthenticated (aggregate-only, no learner data). The SSE bus is in-process (one API worker).

## 8. What was and was not verified in this session

Verified: full backend suite; a real `uvicorn` process with the real lifespan on an **empty** database (catalog auto-seeded: 158 skills /
140 resources / 95 items) driven over HTTP by `scripts/run_journey.py` (live path ×3, seeded path ×2, all steps ok); migration
`0007` compiles to valid PostgreSQL DDL (`alembic upgrade 0006_reflection:0007_observability --sql`); `docker compose config` is valid;
the demo reset (`erase_learner_data`) runs with SQLite foreign keys **enforced** (Postgres enforces them).

**Not verified: `docker compose up --build` end to end.** The first build attempt died mid-way when Docker Desktop's engine dropped
(`rpc error … EOF`); it then would not restart (`docker desktop status` stayed `starting`; the WSL VM was up, the engine never
answered). Nothing in the compose change is expected to be problematic — the API/web images built before this phase, the
changes are additive (mount, env, healthcheck, build args), and the Compose file validates — but "it works in Docker" is
unproven until you run §9's commands. Also not re-run: the Playwright suite (frontend unchanged except its Dockerfile) and any
live-Postgres run of migration `0007`.

## 9. Commands

### Run it

```bash
cp .env.example .env                 # defaults are fine; no API key needed
docker compose up --build            # postgres → api (alembic upgrade head, catalog seeded) → web
curl http://localhost:8000/api/health
open http://localhost:3000
docker compose down                  # add -v to drop the database volume
```

### Demo (design §38; works offline)

```bash
# 1. In .env:  DEMO_MODE=true      (rebuild the web image: docker compose up --build)
docker compose up --build -d
# 2. Rehearsal checklist (graph loaded, links, item bank, scenario ↔ bank consistency, LLM mode):
docker compose exec api python scripts/seed_demo.py --preflight
# 3. Seed / reset the persona "Asha" (also: POST /api/demo/seed):
docker compose exec api python scripts/seed_demo.py
# 4. Walk the beats in the browser (http://localhost:3000, no login needed in dev), or drive them:
curl -X POST localhost:8000/api/demo/scripted-attempt            # step 8-11: misconception → reflection → revision
docker compose exec api python scripts/run_journey.py --iterations 3 --demo-seed     # the whole journey + timings
```

| Beat (design §38.2) | Where |
|---|---|
| 1–2 upload, evidence with spans/tiers | `/start`, `/dashboard/evidence` |
| 3–4 role, gap graph | `/dashboard/skills`, `/dashboard/gaps` |
| 5–6 weekly plan, "Why this step?" | `/dashboard/plan` (Why drawer) |
| 7–8 practice; scripted wrong attempt | `/dashboard/practice`; `POST /api/demo/scripted-attempt` |
| 9–12 misconception → reflection → diff → explanation | trace panel + `AdaptiveMoment` on the plan; `GET /api/decisions/{id}` |
| 13–14 grounded questions | `/dashboard/tutor` — "Why did my plan change?", "Why do I need the chain rule for PyTorch training?" |

Record/replay for a stage demo (needs a real key; not verified against the live API — §7.2):
run once with `LLM_PROVIDER=anthropic`, model ids, `DEMO_MODE=true` (which records) and `docker compose exec api python scripts/run_journey.py
--demo-seed`; then set `REPLAY_MODE=true` to serve recorded responses first (a miss falls through to live, then to the deterministic path).
The fixed persona id keeps prompt hashes stable across rehearsals. Runs are inspectable at `GET /api/runs/{id}` and `GET /api/metrics`.

### Tests

```bash
cd backend && python -m pytest -q                     # everything (572 tests, ~2.5 min)
python -m pytest tests/integration -q                 # the full journey, live + seeded paths
python -m pytest tests/evaluation -q                  # gold sets + oracles; writes reports/evaluation_metrics.{json,md}
python -m pytest tests/security -q                    # injection, uploads, isolation, tools, roles, broken resources
python -m pytest tests/test_observability.py tests/test_llm_gateway.py tests/test_demo_mode.py -q
python ../data/scripts/build_dataset.py && python ../data/scripts/validate_dataset.py   # domain pack (0 errors expected)
cd ../frontend && npm run build && npx eslint . && npx tsc --noEmit                     # frontend
cd ../frontend && npx playwright test                 # needs a live API + `npm run start` (see frontend/README.md)
```

## 10. Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `ENV` | `dev` | `dev` allows the cookie-less `dev-user` fallback; anything else requires a session (401) |
| `DATABASE_URL` | local Postgres | async SQLAlchemy URL (`postgresql+asyncpg://…`; tests use SQLite) |
| `POSTGRES_USER/PASSWORD/DB` | `edupath` | Compose's Postgres |
| `DEMO_MODE` | `false` | enables `/api/demo/seed` + `/api/demo/scripted-attempt`, records live LLM responses, builds the web UI in demo mode |
| `REPLAY_MODE` | `false` | serve recorded LLM responses first (offline / deterministic) |
| `LLM_PROVIDER` | `none` | `none` = deterministic agents; `anthropic` = live |
| `LLM_API_KEY`, `LLM_SMALL/MID/STRONG_MODEL`, `LLM_BASE_URL` | empty / Anthropic URL | provider credentials and per-tier model ids |
| `LLM_TIMEOUT_S` | `8` | live-call timeout before falling back to a recorded/deterministic answer |
| `LLM_RECORD` | `false` | record successful live responses into `llm_replay_entries` (implied by `DEMO_MODE`) |
| `LLM_COST_PER_1K_INPUT_USD`, `…_OUTPUT_USD` | `0` | optional pricing so run records report cost |
| `GITHUB_TOKEN` | empty | optional; raises GitHub API rate limits |
| `DOCUMENT_STORAGE_DIR` | `./storage/documents` | uploaded documents (Compose: a named volume) |
| `DATASET_DIR` | repo `data/dataset` | curated domain pack (Compose: `/data/dataset`) |
| `AUTO_SEED_CATALOG` | `true` | ingest the pack on start iff the catalog is empty |
| `SESSION_SECRET` | dev default | reserved for real auth — currently unused |
| `FRONTEND_ORIGIN` | `http://localhost:3000` | the one CORS origin |
| `NEXT_PUBLIC_API_BASE_URL`, `NEXT_PUBLIC_DEMO_MODE` | localhost:8000 / `false` | **build-time** for the web image (Compose passes them as build args) |
| `LOG_LEVEL` | `INFO` | structured JSON logging |

## 11. Architecture summary

Modular monolith: Next.js ↔ FastAPI ↔ PostgreSQL + pgvector; LangGraph for the three bounded agent graphs (G1 onboarding, G2 planning,
G4 tutor; G3 evidence-response is plain async orchestration because each step's DB write feeds the next read).

```
resume ─▶ Profiler ─▶ Evidence Verifier ─▶ Skill Normalizer ─▶ [human confirm] ─▶ Evidence + LearnerSkillState
                                                                                    │
curated Skill Graph ─▶ Gap Engine (pure) ─▶ objectives ─▶ Retrieval/Ranker ─▶ Planner ─▶ Plan Validator ─▶ Fallback Planner
                                                                                    │
practice (Assessor, item bank) ─▶ grade ─▶ Mastery Updater ─▶ Struggle Classifier ─▶ Reflection Agent ─▶ Reflection Validator
        ─▶ closed operators ─▶ patched plan ─▶ Plan Validator ─▶ PlanRevision + ReflectionRecord + DecisionRecord (revertible)
                                                                                    │
Tutor (9 read-only tools) ─▶ verify_citations ─▶ answer   ·   Report Builder ─▶ ProgressReport
Every request: TraceRunMiddleware ─▶ RunContext ─▶ AgentRun / AgentStep (+ SSE)   ·   LLM Gateway ─▶ live | replay | degrade
```

Five LLM agents; eleven deterministic services own every decision that matters (statuses, mastery, struggle class, validity, ranking,
citations). No agent has a side-effect tool; state changes only through validated commit nodes; `learner_id` always comes from the session.
