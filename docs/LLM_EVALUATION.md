# EduPath — Live LLM Evaluation & Quality Baseline

> Stage 1 of the post-Phase-12b work. Everything below was measured against the **real** configured providers on
> 2026-09-20 (Groq `openai/gpt-oss-20b` / `gpt-oss-120b`, Hugging Face `Qwen3-Embedding-0.6B` and
> `DeepSeek-V4.1-Flash`, Tavily, GitHub). Raw results: [`docs/llm_eval_baseline/`](llm_eval_baseline/). Harness:
> `backend/scripts/evaluate_llm.py` + `backend/tests/evaluation/live/`.

## 1. Purpose

The deterministic evaluation suite (`backend/tests/evaluation`, 601 tests at the start of this stage) pins every provider to
`none`, so it measures the *fallback* paths. It says nothing about what the live models actually produce. This stage adds a
**live mode** that runs the real journey behaviours through the real gateways and records, per case and in aggregate,
whether the model output is usable, how good it is against gold labels where those exist, and what it costs in latency,
retries and provider errors. It changes no product behaviour.

## 2. Methodology

* **Same code, real providers.** Each case drives the actual FastAPI app in-process (ASGI, in-memory SQLite — no real database or
  learner is touched) with the provider settings from `backend/.env`. Nothing is mocked. The catalog is ingested with the live
  embedding provider.
* **Measurement without interference.** `tests/evaluation/live/instrument.py` *wraps* `LLMGateway.complete`, the provider call, the
  agents' `note_retry`, and the embedding / vision / web-search gateways. It records per call: operation, tier, model, latency,
  per-attempt error category (+ `Retry-After`), tokens, degraded/replayed flags, and silent fallbacks. It never alters a request
  or a response. A disabled provider is a hard error in live mode (`LiveConfigError`), never a silent offline run.
* **Setup scaffolding is explicit.** Steps that are not the behaviour under test (e.g. creating the plan a reflection scenario needs,
  building the Tutor's learner history) run inside `setup_mode()`: the LLM provider is refused *without a network call*, the agents
  take their documented deterministic path, and those calls are excluded from every metric. Nothing that is evaluated ever runs in
  setup mode.
* **Hard checks vs quality metrics.** *Hard checks* are invariants the deterministic layer must guarantee whatever the model says
  (plan within budget, every resource real/healthy/aligned, prerequisite order, no forbidden skill committed, every citation real and
  learner-scoped, web results allowlisted/unvetted/kept out of plans, closed operator set, revision committed with a decision
  record…). A violated hard check fails the case. *Quality metrics* (precision, recall, coverage, rubric scores…) are reported, never
  gated.
* **Deterministic grading first; no LLM-as-judge.** Rubrics are code. The single model-based signal is the Assessor's own **blind
  solver** (small tier), reported under an explicit *model-based, not ground truth* label; it is the system's existing validator, not a
  new judge.
* **Case status** — `pass` (live path, all hard checks pass) · `fallback` (a deterministic fallback replaced an unusable model result)
  · `fail` (a hard check or an unexpected exception) · `provider_error` (the case could not be evaluated because the provider was
  throttled/unavailable — *not* a model failure, and excluded from model-behaviour rates) · `skipped`.
* **Pacing.** Cases run sequentially; `--min-interval` and a token-per-minute budget (`--tpm`) space LLM-bearing cases. A case that
  ends in a provider error is re-run **once** after a 75 s cooldown; three breaker trips abort the remaining LLM cases (reported as
  skipped). Gateway retries are the product's own (max 2, `Retry-After` honoured up to 15 s).

## 3. Datasets / fixtures

| Area | Fixture | Size (full suite) |
|---|---|---|
| Profiling, Gap | `tests/evaluation/gold/resumes.json` (expected + forbidden skill ids per resume; includes a no-skills resume, an injection resume, a PII-heavy header) | 10 resumes |
| Planner | 10 personas from the offline plan-validity test, now in `tests/evaluation/live/gold_live.json` (3 roles, 2–20 h/week, modality and session-cap variants) | 10 plans |
| Assessor | first N skills (sorted) that carry catalogued misconceptions; 3 items requested each | 6 skills / 18 items |
| Reflection | every curated misconception the item bank can *confirm* (≥ 2 tagged wrong answers); gold = curated `root_skill_id` + `misconception_id` | 10 misconceptions |
| Tutor | 17 questions (why-changed, concept, gaps, plan, progress, evidence, resource, decision, out-of-scope, 3 adversarial) with coarse expectations (cited ids / id prefix / keyword) | 17 questions |
| Web search | 5 skills through `GET …/web-resources` | 5 queries |
| Vision | a generated 2-page **image-only** PDF (no text layer); gold = page-1 and page-2 skill sets | 1 document |
| Known issues | forged-cookie probe | 1 |

`smoke` = 3 resumes, 2 personas, 2 assessor skills, 2 reflection cases, 6 tutor questions, 2 web skills (22 cases, ≈ 23 K tokens).
`full` = everything (71 cases, ≈ 81 K tokens). Dataset identity: graph `v0.1.0-domain-pack`; gold hash is in every report.

## 4. Metrics

**Technical** (per report and per area): total / successful / fallback / failed / provider-error / skipped cases; schema-valid rate
(model output parsed without falling back); validator-pass rate (draft accepted by the deterministic validator — plan validator,
span verifier, citation verifier, reflection validator, blind solver); fallback rate; retry rate (gateway + schema retries per call);
LLM-call and case latency avg/p50/p95/max; provider errors by category (`rate_limit`, `timeout`, `transport`, `server_error`,
`payload_too_large`, `empty_response`, embedding fallbacks…); tokens.

**Quality** (only where a gold label or a deterministic oracle exists; otherwise `N/A (not scored)` with the reason):

| Area | Metrics |
|---|---|
| A Profiling | skill precision / recall / F1 vs gold; forbidden-skill hits; unsupported-claim rate; fabricated-span drops; injection drops; span presence + exact-offset rate; normalization confidence (right vs wrong); tier distribution; *tier accuracy = N/A (no gold)* |
| B Gap | status agreement, missing-vs-known agreement, gap-set Jaccard, top-5 priority overlap — live-profiled vs gold-profiled learner **at a fixed evidence tier**; prerequisite-order and verify-before-teach invariants. The engine has no LLM: this measures how profiling errors *propagate*. |
| C Planner | final validity; first-attempt validator acceptance; fallback rate; objective coverage (all / top-10); prerequisite order; resource↔skill alignment (`TARGETS` edge); budget adherence + **utilization**; under-filled rate; reason text; **ID provenance**; coherence proxies |
| D Assessment | generation success; first-try schema validity; 10-check deterministic rubric; blind-solver agreement (**model-based**); distractor tag coverage; tag validity; distinct stems; *key/tag correctness = N/A (no gold)* |
| E Reflection | root-cause correct; misconception correct; graph-connected root; closed operator set; edit validity; revised plan uses real resources; evidence grounding; remediation grounding; LLM path used; explanation names the concept |
| F Tutor | citation validity; first-draft citation rejection (unsupported-citation rate); adversarial ids never cited; gold expectations met; out-of-scope handling; conservative-answer rate; unreal ids in text; latency; *free-text correctness = N/A* |
| G Web | executed; results/query; https+allowlist; unvetted; no catalog id / catalog untouched; keyword relevance; exclusion from plans |
| H/I | VLM requests per 2-page PDF, page-1/page-2 recall; cookie forgeability |

## 5. Current baseline (2026-09-20)

**How it was produced.** Three live runs on the same tree (base commit `2abe577`, working tree containing the harness), merged with
per-case provenance (`backend/scripts/evaluate_llm.py --merge …`; each case carries `source_run`):

| Run | UTC | Suite | Result |
|---|---|---|---|
| `run0_smoke` | 11:32 | smoke | 22/22 pass, 23 LLM calls, 0 degraded |
| `run1_full_unpaced` | 11:43 | full | 59 pass · 3 provider-error · 9 skipped (Groq `gpt-oss-120b` **daily token quota exhausted** during the Tutor area) |
| `run2_vision_supplement` | 12:00 | full, `--areas vision` | pass after one cooldown re-run |

Merged: **71 cases · 63 measured & passing · 0 fallback · 0 failed · 3 provider-error · 5 skipped** (all 8 unmeasured cases are Tutor
questions; 9 of 17 Tutor questions were measured). Full tables: [`llm_eval_baseline/baseline_live.md`](llm_eval_baseline/baseline_live.md).

### 5.1 Technical

| Metric | Value |
|---|---|
| Schema-valid rate | 1.000 (n = 45; **0** agent schema-retries) |
| Validator-pass rate | 1.000 (n = 45) |
| Fallback rate (measured cases) | 0.000 (n = 45) |
| LLM gateway calls / degraded | 79 / 4 (all 4 = provider throttling; 3 Tutor + 1 first vision attempt) |
| Gateway retries | 17 (retry rate 0.215 per call; 16.5 % of calls needed ≥ 1 retry) |
| LLM call latency avg / p50 / p95 / max | 2.8 s / 1.3 s / 14.3 s / 17.6 s (n = 75) |
| LLM-bearing case latency p50 / p95 | 4.1 s / 17.7 s |
| Provider errors | 21 × `rate_limit` (LLM attempts); 3 embedding requests silently fell back to the deterministic vector |
| Tokens | ≈ 57 K in / 27 K out across the merged runs |

### 5.2 Quality

| Area | Result |
|---|---|
| **A Profiling** (10 resumes) | precision **0.809**, recall **0.760**, F1 **0.784** (offline deterministic extractor: 0.922 / 0.940). Forbidden-skill hits **0**. Fabricated spans dropped: 0 %. Quoted span present in source: 100 %. Unsupported-claim rate 12.2 %. Normalization confidence 0.984 (correct) vs 0.798 (incorrect). Tiers: 46 × E0, 9 × E1; the "resume alone never above E1" invariant held 10/10. |
| **B Gap** (10) | status agreement **0.996**, gap-set Jaccard 1.000, top-5 priority overlap 1.000; prerequisite-order and verify-before-teach invariants 100 %. |
| **C Planner** (10) | final validity **10/10**; LLM draft accepted on the first attempt **10/10** (0 validator rejections, 0 fallbacks); alignment 100 %; budget adherence 100 %; 0 unsupported resources. **Mean utilization 21.9 %; 9/10 plans under 50 % of the budget; objective coverage 20.9 % (top-10: 22.2 %). ID provenance on plan items: 0 %.** |
| **D Assessment** (6 skills, 18 items) | 18/18 items generated, first-try schema-valid 6/6; rubric pass **97.8 %** (`no_length_cue` 15/18, `skill_aligned` 17/18); blind-solver agreement 100 % (**model-based**); distractor tag coverage 52.9 %; tag validity 100 %. |
| **E Reflection** (10) | root cause correct **10/10**, misconception correct **10/10**, graph-connected 10/10, closed operator set 10/10, edits valid 10/10, evidence grounded 10/10, LLM path used 10/10 (0 deterministic-policy fallbacks), explanation names the concept 9/10. |
| **F Tutor** (9 of 17 measured) | final citations real & learner-scoped **100 %**; first-draft citation rejection 0 %; adversary-supplied ids never cited (1 adversarial probe measured); gold expectations met 100 % of scored expectations (n = 9; the citation-kind expectation on `resource_hinted` was missed in an earlier smoke run — §6.3); p50 / p95 latency 1.4 s / 9.1 s. |
| **G Web** (5 queries) | executed 5/5; 5.0 results/query; https + allowlist 100 %; all `unvetted`; no catalog id and catalog untouched 100 %; keyword relevance 92 %; excluded from all 10 plans. |
| **H Vision** | a 2-page image-only PDF produced **1** VLM request; page-1 recall 1.00, **page-2 recall 0.00**. |
| **I Known issues** | forged `session` cookie **accepted** (confirmed). |

### 5.3 Budget utilization by weekly hours (thin-plan measurement — measured, **not fixed** in this stage)

| Hours | 2 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 12 | 20 |
|---|---|---|---|---|---|---|---|---|---|---|
| Scheduled / budget | 60/120 | 105/240 | 65/300 | 80/360 | 75/420 | 75/480 | 70/540 | 95/600 | 95/720 | 75/1200 |
| Utilization | 50 % | 44 % | 22 % | 22 % | 18 % | 16 % | 13 % | 16 % | 13 % | **6 %** |

The live LLM planner is only marginally better than the offline fallback planner (offline: 38 / 15 / 8 / 4 % at 2 / 5 / 10 / 20 h; live:
50 / 22 / 16 / 6 %): the limit is upstream of the model (the 45-minute session cap removes course-length resources; no segment splitting).

## 6. Findings

### 6.1 What works
* **The "LLMs propose, deterministic code validates" contract held on every measured case.** 0 hard-check violations across 63
  cases: no forbidden/injected skill committed, no plan over budget or with an unreal/broken/misaligned resource, prerequisites
  always ordered, every Reflection edit inside the closed operator set and committed with a decision record, every Tutor citation real.
* **Structured-output reliability is high.** 45/45 model outputs were schema-valid on the first try (0 schema retries), 10/10 plan
  drafts passed the validator first time, 0 fallbacks. (Earlier live debugging fixed the prompts that used to fail; this baseline
  confirms it held.)
* **Reflection** finds the injected root cause and misconception 10/10 with the LLM path (the same accuracy as the deterministic
  policy offline), with grounded evidence and valid revisions.
* **Assessor** generates valid, catalogue-tagged items (18/18) and the blind solver accepts them.
* **Web search** is correctly fenced: allowlisted, unvetted, title-only, never merged into the catalog or a plan.

### 6.2 What is weak
* **Profiling quality is below the deterministic extractor** (F1 0.784 vs ≈ 0.93). The model under-extracts skills stated in narrative
  context (`ml-engineer-project`: recall 0.57 — misses CNN / experiment tracking / model serving) and over-extracts (coursework
  resume: 4 extra skills; the LLM disambiguation step mapped the soft skill "strong communicator" to `skill.data_storytelling`,
  a force-fit design §22.5 says must stay unmapped). It assigns E0 to 46 of 55 claims. Precision is a *lower bound*: the gold
  lists were authored around the catalog-anchored extractor, so some "extras" may be legitimate.
* **Thin plans** (§5.3) — the largest measured product weakness, independent of the model.
* **Plan items carry no ID provenance.** LLM-drafted items get `PlanItemReason(text=…)` only (`orchestration/graphs.py`
  `_drafts_to_plan_items`); `evidence_ids` / `graph_path` / `decision_id` are empty on 100 % of items, although design §16.6
  says IDs are attached deterministically and only the phrasing is LLM-authored.
* **Assessor distractor tagging is unverifiable and may over-tag:** for `skill.docker` all 9 distractors carry the single candidate
  misconception; tag *correctness* cannot be scored without gold. Length cue (key noticeably longer than distractors) in 3/18 items.
* **Latency:** LLM calls are fast (p50 1.3 s) but the tail is dominated by rate-limit backoff (p95 14.3 s); 4 of 10 plan requests
  exceeded the design's 15 s target (17.7 s, 18.7 s, 15.6 s, 17.7 s — each contained exactly one 429 retry on the `PlannerDraft` call).

### 6.3 What is unmeasured
* **8 of 17 Tutor questions** (`gaps_short`, `progress`, `evidence_python`, `resource_backprop`, `decision_explain`, `oos_poem`,
  `adv_fake_skill`, `adv_fake_resource`): the provider quota ran out (§6.5). In particular only 2 of the 5 out-of-scope/adversarial
  probes were measured (`oos_weather`, `adv_fake_evidence`), so refusal and injection-resistance quality is thinly evidenced. Re-run `--areas tutor` after the quota
  refills and `--merge`.
* No gold exists for: evidence-tier assignment, per-skill *levels*, Assessor key correctness and tag correctness, free-text Tutor
  correctness, the small-tier short-answer rubric grader, `narrate_progress`, GitHub-repository profiling. They are reported `N/A`.
* **Run-to-run variance** is not characterized (one run per case). One observed instance: exact character-offset fidelity was 0.857 in
  an earlier smoke run and 1.000 in the next; hosted models are nondeterministic even at temperature 0.
* The *cause* of the 3 silent embedding fallbacks (run 1) was not captured; the harness now records the reason.
* Tutor `resource_hinted`: the pre-fix smoke run named the recommended resource id in the answer text without citing it (expectation missed); the
  later smoke run cited it (expectation met). Coarse citation expectations are sensitive to that.

### 6.4 What fails
Nothing among the 63 measured cases (0 hard-check failures). During development one hard check *did* fail: exact character offsets on a
live claim. That was a wrong invariant in the harness (the Evidence Verifier deliberately accepts spans with ≥ 0.9 similarity, so
offsets can drift by a few characters while the quoted span is genuinely in the document); it is now measured as a quality metric
(100 % exact in the merged baseline, 85.7 % in one earlier run) with the hard invariant being "span present in the source".

### 6.5 Provider / rate-limit related
* **Groq free tier:** 8,000 tokens/min, 1,000 requests/day, **200,000 tokens/day on `gpt-oss-120b`** (limits read from response
  headers and the 429 body). By the end of run 1 the daily quota was exhausted (199.4 K used); it refills continuously at ≈ 2.3 tokens/s
  (≈ 200 K/day), so a full re-run (≈ 81 K tokens) needs hours of headroom. Smoke ≈ 23 K + full ≈ 81 K ≈ 52 % of one day's budget
  before any development iteration.
* 21 `rate_limit` attempts; 17 gateway retries. When the cause is the *daily* quota the `Retry-After` is 5–15 minutes, far above the
  gateway's 15 s cap, so in-request retries cannot help — Tutor answers then degrade to the conservative path (3 cases).
* **`live_smoke.py`** (existing): 6/7 pass; `llm[mid]` got a 429 while the same model passed on the `strong` tier moments later —
  quota, not a regression.
* **Embeddings:** 3 runtime query embeddings (2 profiling cases) fell back to the deterministic hashed vector. The gateway logs it but
  the response is indistinguishable to the caller — a silent quality degradation under provider trouble (also a product issue, 6.6).
* The 429 *body* (TPM vs TPD) was not captured in run 1; the harness now records `Retry-After` per attempt to separate them.

### 6.6 Product / algorithm issues (not model or provider problems)
1. Thin plans (§5.3) — 45-min session cap + no segment splitting.
2. No ID provenance on LLM plan items (6.2).
3. Vision reads **only page 1** (1 VLM request for a 2-page PDF; page-2 recall 0).
4. The `session` cookie is an unsigned user id: a fresh client presenting the same value receives the victim's profile (confirmed).
5. The prompt-injection detector drops *all* claims in a document with an injection window (`injection-mixed-with-real-skills`: 5/5
   dropped, recall 0) — consistent with the offline result, so safe but blunt.
6. LLM skill-disambiguation force-fits unmappable labels (6.2).
7. Silent deterministic fallback of query embeddings (6.5).

## 7. Known limitations of this evaluation

* Small n (10 resumes, 10 personas, 10 misconceptions): treat differences of a few points as noise. No confidence intervals.
* Gold coverage is partial (see 6.3); precision on profiling is a lower bound.
* One run per case; hosted models are nondeterministic. `temperature=0` reduces but does not remove variance.
* Setup scaffolding (Reflection/Tutor learner history) uses the deterministic planner/reflection by design; the *evaluated* calls are live.
* Tutor `gold expectations` are cited-id / keyword checks, not answer correctness.
* The merged baseline combines three runs on the same tree; run 1 predates three harness refinements (cooldown re-run, provider-error
  exclusion from model-behaviour rates, Assessor `validator_pass` redefinition). `--merge` recomputes every aggregate with the current
  code, so the numbers in §5 are consistent; the raw run JSONs are kept as recorded.
* Provider quota shapes what can be run in a day; the harness reports quota loss as `provider_error`/`skipped`, never as a model failure.

## 8. Interpretation rules

1. **`pass` ≠ good.** It means the deterministic guarantees held. Read the quality tables for how good.
2. **`N/A (not scored)` is not zero.** It means no gold/oracle exists. Do not compare it.
3. **Provider-error and skipped cases are excluded from model-behaviour rates** and listed separately; a rate over few cases (see `n`)
   is anecdotal.
4. **Compare like with like:** live vs the offline *reference* values printed in each report (deterministic providers-off run).
5. **Model-based signals** (blind solver) measure agreement between two models, not truth.
6. A regression means a *hard check* newly fails, a fallback/schema-retry rate rises, or a quality metric drops by more than run-to-run
   noise on the same commit — re-run before concluding.

## 9. How to rerun

```bash
cd backend
python scripts/live_smoke.py                                        # existing provider connectivity check (7 services)
python scripts/evaluate_llm.py --mode live --suite smoke            # 22 cases, ≈ 23 K tokens
python scripts/evaluate_llm.py --mode live --suite full             # 71 cases, ≈ 81 K tokens (watch the provider's daily quota)
python scripts/evaluate_llm.py --mode live --suite full --areas tutor,vision   # a subset (e.g. the cases a quota cut short)
python scripts/evaluate_llm.py --merge run_a.json run_b.json --out-name baseline_live   # combine runs, provenance kept; no provider calls
python scripts/evaluate_llm.py --mode offline                       # the existing deterministic evaluation (providers off), unchanged
python -m pytest -q                                                 # 623 deterministic tests incl. the harness's own (tests/test_llm_eval_harness.py)
```

Options: `--areas profiling,gap,planner,assessor,reflection,tutor,web,vision,known_issues` · `--min-interval SEC` (default 2) ·
`--tpm N` token-per-minute pacing budget (default 6000; 0 = off) · `--out-dir` (default `backend/reports/llm_eval/`, gitignored) ·
`--strict` (non-zero exit on provider-error cases too). Exit: 0 unless a hard check failed (1) or live config is invalid (2).
Reports: `<UTC stamp>_<suite>.{json,md}` and `latest_<suite>.{json,md}`. The committed baseline lives in `docs/llm_eval_baseline/`.

## 10. Reproducibility record (baseline)

* Every report records: UTC timestamp, git commit (+ dirty flag), provider/model per tier, embedding and vision models, the
  short content hash of each agent's system prompt (the repo has no prompt-version constants), gold-fixture hash and graph version,
  pacing settings, and per-case/per-call data. No secret is recorded — only credential *names* present (`redact()` scrubs errors;
  a scan of all artifacts found no secret values or token shapes).
* Baseline prompt hashes: profiler `d0a1b32207`, planner `ef9f1d5e60`, assessor `1bd79fddc6`, reflection `ceb7cb8896`, tutor `f26b8bbe8a`.
* Deterministic regression at the time: **623 passed** (601 pre-existing + 22 new harness tests); offline evaluation suite unchanged.
