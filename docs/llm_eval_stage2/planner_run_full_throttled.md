# EduPath live LLM evaluation — live / full

*2026-09-20T13:25:43Z · commit `e528c6a` (dirty tree) · python 3.14.3*

## Configuration

- LLM: `groq` — small `openai/gpt-oss-20b`, mid `openai/gpt-oss-120b`, strong `openai/gpt-oss-120b`
- Embeddings: `huggingface` / `Qwen/Qwen3-Embedding-0.6B` · Vision: `huggingface` / `deepseek-ai/DeepSeek-V4.1-Flash:novita` · Web: `tavily`
- Credentials present (by name only): LLM_API_KEY, HF_TOKEN, TAVILY_API_KEY, GITHUB_TOKEN
- Dataset: graph `v0.1.0-domain-pack`, gold hash `3dfee14d3597` · prompts: profiler `d0a1b32207`, planner `33f740114c`, assessor `1bd79fddc6`, reflection `ceb7cb8896`, tutor `f26b8bbe8a`
- Determinism: temperature 0, but hosted models are **nondeterministic** across runs; treat single-run differences as noise (see LLM_EVALUATION.md).

## Technical metrics

| Metric | Value |
|---|---|
| Total cases | 10 |
| Successful (live path, all hard checks pass) | 1 |
| Completed on a deterministic fallback | 0 |
| Failed (hard check violated / exception) | 0 |
| Not evaluable — provider error | 6 |
| Skipped / aborted | 3 |
| Schema-valid rate | 1.000 (n=1) |
| Validator-pass rate (draft accepted without rejection) | 1.000 (n=1) |
| Fallback rate | 0.000 (n=1) |
| Provider throttling: cases first hit by a provider error and retried once after cooldown | 9 |
| LLM gateway calls / degraded | 17 / 15 |
| Retry rate (gateway + schema retries per call) | 1.765 (gateway retries 30, schema retries 0) |
| LLM call latency avg / p50 / p95 / max (ms) | 2540 / 669 / 4411 / 4411 (n=2) |
| LLM-bearing case latency avg / p50 / p95 (ms) | 4629 / 4629 / 4629 (n=1) |
| Provider errors (LLM attempts, by category) | {"rate_limit": 45} |
| Provider errors (embeddings/vision/web) | {"embeddings": {"fell_back_to_deterministic": 142}} |
| Tokens in / out | 3381 / 1697 |

### Per area

| Area | Cases | pass | fallback | fail | provider err | skipped | LLM calls | p50 case ms |
|---|---|---|---|---|---|---|---|---|
| C. Planner | 10 | 1 | 0 | 0 | 6 | 3 | 7 | 31419 |

## Quality metrics

### C. Planner

| Metric | Live value | n | Note |
|---|---|---|---|
| final plan validity (all hard checks) | 1.000 | 1 | budget, referential integrity, alignment, order, non-empty |
| LLM draft accepted by validator on first attempt | 1.000 | 1 |  |
| fallback-planner rate | 0.000 | 1 | deterministic planner replaced the LLM plan |
| validator rejections (drafts) | 0 | 1 |  |
| objective coverage (all objectives) | 0.200 | 1 | budget-limited by design |
| objective coverage (top-10 by priority) | 0.300 | 1 |  |
| prerequisite ordering | 1.000 | 1 |  |
| resource/skill alignment (TARGETS edge exists) | 1.000 | 1 |  |
| time-budget adherence (<= budget) | 1.000 | 1 |  |
| unsupported resources scheduled | 0 | 1 | must be 0 |
| items with a reason text | 1.000 | 1 | LLM-phrased, display only |
| items with ID provenance (graph_path / evidence_ids / decision_id) | 1.000 | 1 | design 16.6 says IDs are attached deterministically |
| mean budget utilization | 0.704 | 1 | of hours*60 (Stage 1 baseline: 0.219); Stage 2 sessionization targets acceptable, not maximal, use |
| mean utilization of the planner's own (0.9-slack) budget | 0.782 | 1 |  |
| resource items with session provenance | 1.000 | 1 | Stage 2: must be 1.0 |
| sessions matching the catalog-derived session (problems) | 0 | 1 | recomputed from the raw catalog row; must be 0 |
| duplicate sessions / resources over-consumed | 0 | 1 | must be 0 |
| minutes added by the deterministic top-up (share of scheduled) | 0.000 | 1 | the rest was selected by the model (or the fallback planner) |
| distinct resources per plan (mean) | 4.000 | 1 |  |
| plans under-filled (< 50% of budget) | 0.000 | 1 |  |
| coherence: overall reason present, no duplicate items | 1.000 | 1 | deterministic proxy; no LLM judge |

Budget utilization by weekly hours (thin-plan measurement; offline fallback baseline was 38% / 15% / 8% / 4% at 2/5/10/20 h):

| Case | Hours | Scheduled min | Budget min | Utilization | Fallback |
|---|---|---|---|---|---|
| plan-ml-tiny-2h | 2 | 88 | 120 | 73% | True |
| plan-da-novice-4h | 4 | 155 | 240 | 65% | True |
| plan-ml-novice-5h | 5 | 188 | 300 | 63% | True |
| plan-ml-claims-8h | 8 | 309 | 480 | 64% | True |
| plan-be-short-sessions | 9 | 380 | 540 | 70% | False |
| plan-da-10h | 10 | 415 | 600 | 69% | True |
| plan-ml-heavy-20h | 20 | 705 | 1200 | 59% | True |

### Offline (deterministic, providers disabled) reference values

| Offline metric | Offline value |
|---|---|
| Evidence / skill precision vs gold | 0.9216 |
| Evidence / skill recall vs gold | 0.94 |
| Reflection / correct root-cause node rate | 1.0 |
| Tutor / citation-existence rate | 1.0 |
| Plan / budget utilization at 2/5/10/20 h per week | 73% / 59% / 66% / 59% |

## Cases that did not pass

| Area | Case | Status | Detail |
|---|---|---|---|
| planner | plan-ml-novice-5h | provider_error | LLM degraded: rate_limit (retried once after cooldown) |
| planner | plan-ml-claims-8h | provider_error | LLM degraded: rate_limit (retried once after cooldown) |
| planner | plan-ml-heavy-20h | provider_error | LLM degraded: rate_limit (retried once after cooldown) |
| planner | plan-ml-tiny-2h | provider_error | LLM degraded: rate_limit (retried once after cooldown) |
| planner | plan-da-10h | provider_error | LLM degraded: rate_limit (retried once after cooldown) |
| planner | plan-da-novice-4h | provider_error | LLM degraded: rate_limit (retried once after cooldown) |
| planner | plan-be-12h | skipped | aborted: the provider stayed rate-limited after repeated cooldowns |
| planner | plan-be-watch-6h | skipped | aborted: the provider stayed rate-limited after repeated cooldowns |
| planner | plan-da-read-7h | skipped | aborted: the provider stayed rate-limited after repeated cooldowns |

## Human-readable examples

**C. Planner**

- `plan-be-short-sessions`: `{"persona": "be-short-sessions", "hours": 9, "utilization": "380/540 min", "session_problems": [], "topup": "0 items / 0 min", "degraded(fallback)": false, "validator_rejections": [], "first_items": [["resource", "skill.http_fundamentals", "res.mdn_http_overview", 30, 1], ["resource", "skill.sql_fundamentals", "res.sqlbolt", 30, 1], ["resource", "skill.programming_fundamentals", "res.py_tutorial", 30, 1]], "reason": "Focused on core HTTP, SQL, and Python fundamentals within budget."}`

- `plan-ml-novice-5h`: `{"persona": "ml-novice-5h", "hours": 5, "utilization": "188/300 min", "session_problems": [], "topup": "0 items / 0 min", "degraded(fallback)": true, "validator_rejections": [], "first_items": [["resource", "skill.python", "res.py_tutorial", 45, 1], ["practice", "skill.python", null, 10, 3], ["resource", "skill.algebra_basics", "res.khan_algebra", 43, 2]], "reason": "Generated by the deterministic fallback planner: objectives ordered by priority and prerequisite layer, budget-fit greedily, no LLM narration."}`

## LLM calls by schema

| Schema | Tier | Calls | Degraded | Avg latency ms | Retried |
|---|---|---|---|---|---|
| PlannerDraft | mid | 16 | 15 | 4411 | 15 |
| SkillDisambiguation | small | 1 | 0 | 669 | 0 |

