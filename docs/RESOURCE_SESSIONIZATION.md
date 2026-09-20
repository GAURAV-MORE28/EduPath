# EduPath — Resource Sessionization (Stage 2)

> Stage 2 of the post-Phase-12b work: "Thin plans, large budgets & resource sessionization".
> Baseline (Stage 1, live providers, [`LLM_EVALUATION.md`](LLM_EVALUATION.md) §5.3): mean budget utilization **21.9 %**
> (6 % at 20 h/week), 10/10 drafts accepted first time, 0 hard-check failures, 0 % plan items with ID provenance.

## 1. Root cause (measured before any change)

Diagnosed on the 10 Stage-1 personas with the deterministic providers, using throwaway diagnostic scripts (not committed); the per-persona
counts below come from those. `tests/test_plan_sessions_integration.py::test_long_catalog_resources_are_offered_as_real_sessions_instead_of_being_dropped`
guards the qualitative claim (more objectives have candidates once sessions are offered). Five separate mechanisms stack; the 45-minute cap is only the first:

| # | Mechanism | Evidence |
|---|---|---|
| 1 | **Hard duration filter.** `ranker.eligibility_checks` sets `duration_ok = duration_min <= session_cap`. Any course-length resource is *removed from the candidate pool*, not shortened. | 61 of the 140 catalog resources are longer than 45 min (25 of 121–300 min, 9 of > 300 min, max 900). Per persona only **1–3 of 9–15 lesson objectives** kept ≥ 1 eligible resource at the cap; with the filter lifted **5–7** do. |
| 2 | **One resource per objective.** The fallback takes `resources[0]`; the LLM prompt says *"use each resource_id at most once"* and *"use the chosen resource's duration_min as est_minutes"*. Nothing lets a plan continue a resource or stack a second one. | Plans contain 1–4 items (live) / 1–3 items (offline fallback) regardless of budget. |
| 3 | **Breadth is capped by a correct hard rule.** V5 allows at most 3 new (non-MET) skills per week (2 for novices). More hours therefore cannot buy more skills — only more *depth* per skill. | Live 20 h persona: 2 items / 75 min. |
| 4 | **No utilization objective anywhere.** Neither the prompt, the fallback nor the validator has a notion of "enough of the budget used". | 9/10 live plans < 50 % of budget. |
| 5 | **No sub-resource structure exists in the catalog.** `data/dataset/resources.json` has no chapter/module/section field, so a long resource can only be divided by time. | field census of all 140 rows. |

Supply is not the bottleneck once (1) is fixed: the best three skills of every persona have 940–1 120 min of eligible material
(`supply nocap top3skills` column), i.e. enough for ≈ 17–20 h of the 0.9-slack budget.

The live LLM planner was only marginally better than the offline fallback (live 50/22/16/6 % vs offline 38/15/8/4 % at 2/5/10/20 h):
both are starved by (1)+(2), so the fix is upstream of the model.

## 2. What a session is (data model)

A **resource session** is a *planning unit derived from one real catalog resource*. It is computed by `app/planning/sessions.py`
(pure functions, no DB/gateway/LLM) from the resource's own `duration_min` and the learner's session length. It is never authored by a
model and never stored as a catalog row.

| Field | Meaning |
|---|---|
| `session_id` | `"<resource_id>#<n>"`, `n` = 1-based position. The only id format. Stable across weeks. |
| `resource_id`, `index`, `count` | the real resource, this session's position, how many sessions the whole resource divides into |
| `est_minutes` | this session's length (fixed by code; a model cannot change it) |
| `start_min`, `end_min` | *nominal* minute range within the resource's **estimated** duration. Not a chapter boundary. |
| `resource_duration_min` | the original, unsplit duration |
| `label` | whole resource → its title. Segment → `"<title> — Study Segment n of N"`. **Never an invented chapter name** (the catalog has none). |
| `title, provider (source), url, modality, resource_type, difficulty, skill_id, curation_tier, provenance="catalog"` | copied from the resource row / the `TARGETS` edge the candidate was generated for |

`ResourceCandidateInfo` (`app/planning/candidates.py`) now carries `sessions` (the ones still to study this week). `PlanItem` gains an
optional `session: PlanItemSession` (`session_id, resource_id, index, count, label, start_min, end_min, resource_duration_min`),
persisted in a nullable JSON column `plan_items.session` (migration `0008_plan_item_session`). Old rows and items without a session stay
valid unchanged. The field is additive on the API; the frontend was not modified.

## 3. Segmentation rules (deterministic, configurable)

`SessionizationPolicy(max_session_minutes, min_session_minutes)`; defaults in `app/core/thresholds.py`
(`DEFAULT_SESSION_CAP_MINUTES=45`, `SESSION_MIN_MINUTES=20`, `SESSION_MAX_MINUTES=60`). `max` is the learner's own
`session_length_min`, bounded to `[1, 60]`.

1. `duration <= max` → **one complete session**; never split, however short (a 15-min article stays whole).
2. otherwise `n = ceil(duration / max)` segments of near-equal length (sizes differ by at most one minute).
3. Every segment is `<= max` (hard) and `>= max // 2`, so none is absurdly small. `min_session_minutes` is enforced as
   `min(min_session_minutes, max // 2)` so a small learner cap stays feasible. **Property-tested for every duration 1–1000 × cap 5–60**
   (`tests/test_resource_sessions.py`).
4. Non-positive duration → no sessions (nothing to study).
5. Segmentation depends only on `(duration, policy)`, so the validator recomputes it independently of whoever proposed a plan.

Skill alignment, prerequisites and objective coverage are **not** used to *cut* a resource (there is no sub-resource structure to align
to); they are enforced where they belong: the Retriever's `TARGETS`/level-band eligibility decides *whether* a resource is a candidate, and
the validator's V3/V5 decide *whether the plan is allowed*. The weekly budget bounds how many sessions are *taken*, not how a resource is
divided, so session ids and numbering are stable across weeks.

## 4. Planner behaviour

Pipeline (G2, `app/orchestration/graphs.py`); ★ = changed in Stage 2:

```
build_objectives → retrieve_candidates ★ → plan_draft ★ → validate_plan ★ → [★ deterministic top-up → re-validate] → provenance ★ → commit
                                              (LLM unusable) → fallback_plan ★ ────────────────────────────────────↗
```

* **Candidates** ★: `recommend_for_skill(..., sessionizable=True)` no longer drops a resource for being longer than the cap; ranking
  (`level_fit`, `quality`, `relevance`, `duration_fit`, …) is unchanged, so a short complete resource still ranks ahead of an otherwise equal
  course. Each ranked resource is then sessionized once, **before any LLM call**. Sessions the learner already marked `done` in an earlier
  week are removed (`PlanningRepository.list_completed_session_ids`), so a long resource continues where it left off; a resource with nothing
  left is dropped. Planned-but-not-done sessions are re-offered (rolling horizon, design §16.1).
* **LLM path** ★: the prompt lists each resource compactly (`sessions`, `minutes_each`, `total_min`, `first_n`), not id by id. The model
  emits `session_id = "<resource_id>#<n>"`. The strict parser resolves it against the real session table (unknown id, a session that does not
  belong to `resource_id`, or a multi-session resource with no `session_id` → `PlannerParseError` → the existing retry) and **takes
  `est_minutes` from the session, not from the model**. The system prompt states a utilization goal (≈ 80 % of the budget with the
  highest-value material; never pad).
* **Deterministic top-up** ★ (`app/planning/fill.py::extend_plan`): if the validated draft is below the acceptable utilization, add the *next
  in-order sessions of the objectives the model already chose* (then the next-ranked resource of the same objective, up to
  `PLAN_MAX_RESOURCES_PER_OBJECTIVE = 3`). It never adds a skill (V5 unaffected), never skips or repeats a session, never reuses a resource
  another objective is using, and never takes the plan above the ceiling. The extended plan is **re-validated**; if any hard rule fails the
  extension is discarded and the validated draft is kept. It costs **no extra LLM call**, is recorded as a `Plan Filler` trace step, and
  `overall_reason` says so.
* **Fallback planner** ★ (`app/planning/fallback.py`): Phase A is design §16.4's loop unchanged (one unit per objective: the first session
  of the best resource); Phase B is the same `extend_plan`. Practice items follow the last study session of their skill. Days are spread by
  `DayPlanner` (each day fills to an even share of the target; a chain of sessions never goes backwards).
* **Acceptable utilization, not maximal** ★: `PLAN_TARGET_UTILIZATION = 0.80` of the effective (0.9-slack) budget is a **ceiling** for the
  fill. The remaining ≈ 20 % is deliberate headroom: with plans filled to ≈ 96 % the demo's Reflection revision could not insert its
  remediation (its patched plan must still pass V1) and correctly refused — found by the regression suite in this stage and fixed by the
  ceiling. A plan that is short because eligible material ran out, or because V5 bounds breadth, is left short.
* **Provenance** ★ (`attach_reason_provenance`): design §16.6 says IDs are attached deterministically. Every final item now gets
  `reason.evidence_ids` (the gap report's evidence for the skill) and `reason.graph_path` (in-scope hard prerequisites, then the skill),
  overwriting anything a model supplied; the model only phrases `reason.text`.

## 5. Validation rules

New **hard** rule `V_session_provenance` (`enforce_sessions=True`; set by the Planning graph, *not* by Reflection's patch validation, which
keeps its permissive candidate sets):

* every resource item has a `session`, and it is a session the objective's candidate set really offers (real resource, real id);
* the session metadata equals the catalog-derived session (a forged label / chapter title is caught);
* `est_minutes` equals the session's own duration (≤ the learner's cap);
* a session appears at most once in the plan (also across objectives);
* a resource's sessions are studied in order (a later session never on an earlier day) and **without skipping ahead** (what is scheduled is a
  prefix of what is still to study);
* total consumption of a resource ≤ its original duration.

`V_DUP` now keys on `(skill, resource, session_id)`, so several *different* sessions of one resource are not a duplicate; the same session
is. New **soft** rule `V_acceptable_utilization`: flagged only when the plan is below `PLAN_MIN_ACCEPTABLE_UTILIZATION = 0.60` **and** in-order
material for its own objectives would still have fit. All existing rules (V1–V5, V_DUP, V6–V10) are unchanged and enforced on every path.

## 6. What the LLM can and cannot do

*Can:* choose objectives, resources and which sessions (by id) to schedule, sequence them across days, phrase `reason_text`.
*Cannot:* create a resource, URL, session id, chapter or section name, duration or any metadata — all of it is derived from the catalog row
before the call and re-checked after it. **Web results** (Tavily) still never reach a plan: they stay `unvetted`, title-only and outside the
catalog (LLM_EVALUATION §6.1). Only catalog rows are sessionized, so `Tavily → validation/curation → catalog → sessionization → planner` is
the only possible route; nothing goes `Tavily → plan`.

## 7. Limitations

* **No real chapter structure.** Sessions are time slices of a resource, labelled neutrally; `start_min`/`end_min` are nominal. If the catalog
  later gains module/lesson metadata, `segment_durations` is the one place to align cuts to it.
* A long resource is only as good as its duration estimate; a "session" of a book is a time slice, not a reading assignment.
* Only a `done` item consumes a session. Multi-week continuation therefore depends on that status being set (tested through the DB); this
  stage did not touch how items get marked done.
* Reflection's own inserted items (remediation/probes) and its `split` operator are outside sessionization and are validated without
  `enforce_sessions`. A revision also has no "make room" operator, hence the headroom ceiling.
* Supply can still bound a plan: the 3-skill cap (V5) plus the catalog's material for the chosen skills. Selection stays priority-first, so a
  large-budget learner whose top-priority skills have little material gets a plan below the ceiling rather than lower-priority filler.
* The frontend does not yet display `session.label`; the API exposes it.

## 8. Results (measured 2026-09-20)

### 8.1 Deterministic (provider-off) — same 10 Stage-1 personas, fallback planner, real catalog

Raw utilization = scheduled minutes / (weekly hours × 60), the Stage-1 definition (the planner's own budget is 0.9 of that; the fill ceiling is
0.8 of *that*, i.e. ≈ 72 % raw at most).

| Persona (h/week) | 2 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 12 | 20 | **mean** |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Before (min) | 45 | 65 | 45 | 115 | 65 | 45 | 30 | 65 | 115 | 45 | |
| After (min) | 88 | 155 | 188 | 215 | 270 | 309 | 370 | 415 | 485 | 705 | |
| Before | 38 % | 27 % | 15 % | 32 % | 15 % | 9 % | 6 % | 11 % | 16 % | 4 % | **17.2 %** |
| After | 73 % | 65 % | 63 % | 60 % | 64 % | 64 % | 69 % | 69 % | 67 % | 59 % | **65.3 %** |

(columns are the personas sorted by weekly hours: ml-tiny-2h, da-novice-4h, ml-novice-5h, be-watch-6h, da-read-7h, ml-claims-8h, be-short-sessions,
da-10h, be-12h, ml-heavy-20h.) Items per plan went from 1–3 to 2–16. All hard checks hold (budget, referential integrity, prerequisite order, no BLOCKED
skill scheduled, every resource real and healthy) on all 10; every resource item carries a session that matches an independent recomputation
from the raw catalog row; 0 duplicate sessions; 0 resources over-consumed; every item has ID provenance. The 20 h persona (59 %) is
**supply-limited by design**: its three highest-priority schedulable skills have 705 min of eligible material in total and every session of it was scheduled.

Deterministic suite: **623 → 686 passed** (+63: `test_resource_sessions.py` 13, `test_plan_sessions.py` 39, `test_plan_sessions_integration.py` 11; the
offline evaluation gained a thin-plan regression guard). Mutation checks confirmed the new validator/fill tests fail when the rule they guard is
removed (session rule, duration check, skip-ahead check, utilization ceiling).

### 8.2 Live providers (Groq `gpt-oss-120b` planner, Hugging Face embeddings, real catalog) — **partial, provider-limited**

The focused planner evaluation was run on the final code but could **not** be completed: the Groq daily token bucket was drained
(`429`, `Retry-After` ≈ 710–760 s on every attempt) and, in one run, Hugging Face embeddings returned `402` (142 of 143 catalog embeddings fell
back to the deterministic vector). That is provider/account state, not planner behaviour; the harness reports such cases as `provider_error`,
excluded from model-behaviour rates. What was measured (raw files in `docs/llm_eval_stage2/`):

| Evidence | Result |
|---|---|
| **LLM path**, `be-short-sessions` (9 h, 30-min sessions), final code, embeddings degraded | draft accepted **first attempt**, 0 validator rejections, no fallback; the model itself selected **13 real session items over 4 resources** (380/540 min = **70 %** vs **13 %** in Stage 1); 13/13 items with session + ID provenance, 0 session problems, 0 duplicates, all 8 hard checks pass; the top-up was not needed (0 min). *n = 1.* |
| **LLM path**, earlier run on pre-fix code (log lines only, metrics not saved because the run was stopped) | `ml-novice-5h` pass, `ml-claims-8h` pass; `da-10h` **failed the new `no_duplicate_sessions` check** → root-caused to a real bug (below) |
| **Provider failure → fallback (row H)**, live embeddings, Groq 429 | `ml-claims-8h` **309/480 = 64 %** (Stage 1 live: 16 %), `be-12h` **490/720 = 68 %** (Stage 1 live: 13 %); all hard checks pass, sessions valid. Recorded as `provider_error` cases, so *not* counted as model behaviour. |
| Fallback-rate | Not comparable: only 1 model-behaviour case completed (0 fallbacks). The Stage-1 rate was 0/10; it did not rise in what was measured, but this is **not** evidence about the rate. |

**Not measured live:** the other 9 personas on the LLM path, the top-up's real-world contribution, prompt-size effects on a full run, and a
before/after comparison of the fallback rate. Re-run `python scripts/evaluate_llm.py --mode live --suite full --areas planner` after the Groq
quota refills (≈ 55 K tokens) and compare against `docs/llm_eval_baseline/baseline_live.json`.

### 8.3 Defects found and fixed during the stage

1. **Shared resource studied twice (found by the live run).** One catalog resource can `TARGET` two skills (`res.khan_stats` →
   `descriptive_statistics` and `probability_fundamentals`); the fallback's Phase A picked it as the top resource for both and scheduled the same sessions
   under two objectives (personas `da-10h`, `da-read-7h`). The validator would have rejected this on the LLM path, but the fallback is not re-validated at
   runtime and the hand-built unit fixtures never shared a resource. Fix: Phase A skips a resource another objective already took (an objective whose only
   material is taken is skipped, not duplicated). Regression tests: unit + all-ten-personas API test.
2. **Filled plans starved Reflection (found by the regression suite).** With plans at ≈ 96 % of the budget the demo's Reflection could not insert remediation (V1) and
   fell back to `needs_attention`. Fix: the fill target is a **ceiling** (0.80), leaving reactive headroom.
3. **Stale "KNOWN LIMITATION" note** in the offline evaluation removed and replaced by a thin-plan regression assertion.

### 8.4 Success criteria

| # | Criterion | Status |
|---|---|---|
| 1 | Utilization materially above 21.9 % | **Met on the deterministic path (17.2 % → 65.3 %); live LLM path n = 1 (13 % → 70 %) — full live comparison pending provider quota** |
| 2 | 0 hard-check failures | Met in everything measured (10/10 offline, 1/1 live LLM, 2/2 live fallback); one hard-check *failure* was observed and fixed (8.3.1) |
| 3 | Fallback rate not increased | Not demonstrable live (n = 1); by design the fallback is used only when the model output is unusable, unchanged |
| 4 | Provenance on every item/session | Met (validator-enforced; 100 % in all measured plans) |
| 5 | No invented structure | Met (parser + validator reject; independent recomputation in tests and harness) |
| 6 | Skill coverage / prerequisite order not regressed | Prerequisite order: 0 violations everywhere measured. Objective coverage by count is unchanged in nature (V5 caps skills); not separately re-measured live |
| 7 | Small-budget plans remain good | 2 h and 4 h plans valid and larger (73 % / 65 %); a whole short resource is still one complete item (unit test) |
| 8 | Focused live planner evaluation run | **Run; only partially completed (provider quota)** — see 8.2 |
