# EduPath live LLM evaluation — live / full (merged)

*2026-09-20T11:43:13Z · commit `2abe577` (dirty tree) · python 3.14.3*

## Configuration

- LLM: `groq` — small `openai/gpt-oss-20b`, mid `openai/gpt-oss-120b`, strong `openai/gpt-oss-120b`
- Embeddings: `huggingface` / `Qwen/Qwen3-Embedding-0.6B` · Vision: `huggingface` / `deepseek-ai/DeepSeek-V4.1-Flash:novita` · Web: `tavily`
- Credentials present (by name only): LLM_API_KEY, HF_TOKEN, TAVILY_API_KEY, GITHUB_TOKEN
- Dataset: graph `v0.1.0-domain-pack`, gold hash `3dfee14d3597` · prompts: profiler `d0a1b32207`, planner `ef9f1d5e60`, assessor `1bd79fddc6`, reflection `ceb7cb8896`, tutor `f26b8bbe8a`
- Determinism: temperature 0, but hosted models are **nondeterministic** across runs; treat single-run differences as noise (see LLM_EVALUATION.md).

## Technical metrics

| Metric | Value |
|---|---|
| Total cases | 71 |
| Successful (live path, all hard checks pass) | 63 |
| Completed on a deterministic fallback | 0 |
| Failed (hard check violated / exception) | 0 |
| Not evaluable — provider error | 3 |
| Skipped / aborted | 5 |
| Schema-valid rate | 1.000 (n=45) |
| Validator-pass rate (draft accepted without rejection) | 1.000 (n=45) |
| Fallback rate | 0.000 (n=45) |
| Provider throttling: cases first hit by a provider error and retried once after cooldown | 1 |
| LLM gateway calls / degraded | 79 / 4 |
| Retry rate (gateway + schema retries per call) | 0.215 (gateway retries 17, schema retries 0) |
| LLM call latency avg / p50 / p95 / max (ms) | 2784 / 1327 / 14333 / 17563 (n=75) |
| LLM-bearing case latency avg / p50 / p95 (ms) | 5706 / 4080 / 17738 (n=45) |
| Provider errors (LLM attempts, by category) | {"rate_limit": 21} |
| Provider errors (embeddings/vision/web) | {"embeddings": {"fell_back_to_deterministic": 3}} |
| Tokens in / out | 57324 / 26973 |

### Per area

| Area | Cases | pass | fallback | fail | provider err | skipped | LLM calls | p50 case ms |
|---|---|---|---|---|---|---|---|---|
| A. Profiling | 10 | 10 | 0 | 0 | 0 | 0 | 21 | 4102 |
| B. Gap analysis | 10 | 10 | 0 | 0 | 0 | 0 | 0 | 6.000 |
| C. Planner | 10 | 10 | 0 | 0 | 0 | 0 | 11 | 6773 |
| D. Assessment | 6 | 6 | 0 | 0 | 0 | 0 | 24 | 4323 |
| E. Reflection | 10 | 10 | 0 | 0 | 0 | 0 | 10 | 1779 |
| F. Tutor | 17 | 9 | 0 | 0 | 3 | 5 | 11 | 1671 |
| G. Web search | 6 | 6 | 0 | 0 | 0 | 0 | 0 | 1125 |
| H. Vision (known limitation probe) | 1 | 1 | 0 | 0 | 0 | 0 | 1 | 5243 |
| I. Known-issue probes | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 31.000 |

## Quality metrics

### A. Profiling

| Metric | Live value | n | Note |
|---|---|---|---|
| skill precision (micro) | 0.809 | 10 | tp=38 fp=9 |
| skill recall (micro) | 0.760 | 10 | tp=38 fn=12 |
| skill F1 | 0.784 | 10 | skill identification accuracy vs gold |
| forbidden-skill hits (injection / negatives) | 0 | 10 | must be 0 |
| unsupported-claim rate (span does not contain skill label/alias) | 0.122 | 10 | heuristic literal check |
| LLM claims dropped by span verification (fabricated/unverifiable) | 0.000 | 10 | hallucinated-span rate |
| prompt-injection claims dropped | 5 | 10 |  |
| quoted span present in source document | 1.000 | 10 | hard invariant (Evidence Verifier) |
| exact character offsets (scrubbed[start:end] == span) | 1.000 | 10 | verifier accepts >= 0.9 similarity, so live-LLM offsets may drift |
| first-try schema-valid rate | 1.000 | 10 | no agent retry needed |
| normalization confidence: correct vs incorrect skills | 0.984 vs 0.798 | 49 | calibration hint: correct should exceed incorrect |
| evidence-tier distribution (E0/E1) | {"E0": 46, "E1": 9} | 55 |  |
| evidence-tier assignment accuracy | N/A | 0 | N/A (not scored): no gold tier labels; only the invariant 'resume alone never above E1' is checked |
| resume-alone-never-above-E1 invariant | 1.000 | 10 |  |

### B. Gap analysis

| Metric | Live value | n | Note |
|---|---|---|---|
| status agreement, live-profiled vs gold-profiled learner | 0.996 | 10 | tier held at E1; isolates skill-identification error |
| missing-vs-known agreement | 0.996 | 10 |  |
| gap-set Jaccard (micro) | 1.000 | 10 | non-MET skill sets |
| top-5 priority overlap | 1.000 | 10 | prioritization |
| prerequisite ordering consistency | 1.000 | 10 | API report |
| verify-before-teach objective typing | 1.000 | 10 |  |
| required-skill / skill-level accuracy vs an independent gold | N/A | 0 | N/A (not scored): the engine is deterministic and verified against an oracle in the offline suite (tests/evaluation); no LLM output to score |

### C. Planner

| Metric | Live value | n | Note |
|---|---|---|---|
| final plan validity (all hard checks) | 1.000 | 10 | budget, referential integrity, alignment, order, non-empty |
| LLM draft accepted by validator on first attempt | 1.000 | 10 |  |
| fallback-planner rate | 0.000 | 10 | deterministic planner replaced the LLM plan |
| validator rejections (drafts) | 0 | 10 |  |
| objective coverage (all objectives) | 0.209 | 10 | budget-limited by design |
| objective coverage (top-10 by priority) | 0.222 | 10 |  |
| prerequisite ordering | 1.000 | 10 |  |
| resource/skill alignment (TARGETS edge exists) | 1.000 | 10 |  |
| time-budget adherence (<= budget) | 1.000 | 10 |  |
| unsupported resources scheduled | 0 | 10 | must be 0 |
| items with a reason text | 1.000 | 10 | LLM-phrased, display only |
| items with ID provenance (graph_path / evidence_ids / decision_id) | 0.000 | 10 | design 16.6 says IDs are attached deterministically |
| mean budget utilization | 0.219 | 10 | KNOWN LIMITATION (thin plans): measured, not fixed in this stage |
| plans under-filled (< 50% of budget) | 0.900 | 10 |  |
| coherence: overall reason present, no duplicate items | 1.000 | 10 | deterministic proxy; no LLM judge |

Budget utilization by weekly hours (thin-plan measurement; offline fallback baseline was 38% / 15% / 8% / 4% at 2/5/10/20 h):

| Case | Hours | Scheduled min | Budget min | Utilization | Fallback |
|---|---|---|---|---|---|
| plan-ml-tiny-2h | 2 | 60 | 120 | 50% | False |
| plan-da-novice-4h | 4 | 105 | 240 | 44% | False |
| plan-ml-novice-5h | 5 | 65 | 300 | 22% | False |
| plan-be-watch-6h | 6 | 80 | 360 | 22% | False |
| plan-da-read-7h | 7 | 75 | 420 | 18% | False |
| plan-ml-claims-8h | 8 | 75 | 480 | 16% | False |
| plan-be-short-sessions | 9 | 70 | 540 | 13% | False |
| plan-da-10h | 10 | 95 | 600 | 16% | False |
| plan-be-12h | 12 | 95 | 720 | 13% | False |
| plan-ml-heavy-20h | 20 | 75 | 1200 | 6% | False |

### D. Assessment

| Metric | Live value | n | Note |
|---|---|---|---|
| item generation succeeded (>= 1 valid item) | 1.000 | 6 |  |
| items generated / requested | 1.000 | 6 |  |
| first-try schema-valid rate | 1.000 | 6 |  |
| deterministic rubric pass rate | 0.978 | 6 | 10 checks per item (see per-check table) |
| blind-solver agreement (MODEL-BASED, small tier; not ground truth) | 1.000 | 6 | key correctness proxy |
| distractor misconception-tag coverage | 0.529 | 6 | share of distractors tagged |
| misconception-tag validity (only catalogued ids) | 1.000 | 6 |  |
| distinct stems within a batch | 1.000 | 6 |  |
| key-correctness / distractor-plausibility vs gold | N/A | 0 | N/A (not scored): no gold-labelled generated items; blind solver is the only (model-based) signal |
| misconception-tag *correctness* (right misconception for the distractor) | N/A | 0 | N/A (not scored): no gold labels for generated distractors |
| per-check rubric pass counts | {"distractors_differ_from_key": "18/18", "exactly_one_key": "18/18", "explanation_present": "18/18", "key_untagged": "18/18", "no_all_or_none_of_the_above": "18/18", "no_length_cue": "15/18", "options_3_to_5": "18/18", "options_distinct": "18/18", "skill_aligned": "17/18", "tags_are_catalogued": "18/18"} | 180 |  |

### E. Reflection

| Metric | Live value | n | Note |
|---|---|---|---|
| root-cause skill correct (== injected) | 1.000 | 10 | gold: curated misconception -> root skill |
| misconception identified correctly | 1.000 | 10 | gold: injected misconception id |
| root cause graph-connected to struggling skill | 1.000 | 10 |  |
| operators within the closed set | 1.000 | 10 |  |
| plan-edit validity (committed + decision recorded) | 1.000 | 10 |  |
| revised plan references real resources | 1.000 | 10 |  |
| evidence grounding (decision cites known signals/assessments) | 1.000 | 10 |  |
| remediation resources catalogued for the misconception | 1.000 | 10 |  |
| LLM path used (no deterministic-policy fallback) | 1.000 | 10 |  |
| learner explanation names the concept (root/struggling skill or misconception topic) | 0.900 | 10 | coarse keyword check |

### F. Tutor

| Metric | Live value | n | Note |
|---|---|---|---|
| final citations real & learner-scoped | 1.000 | 9 | code-enforced; must be 1.0 |
| unsupported-citation rate (first draft rejected by verifier) | 0.000 | 9 | the verifier then forces a regeneration or conservative answer |
| adversary-supplied ids never cited | 1.000 | 9 |  |
| gold expectations met (cited ids / keywords) | 1.000 | 9 | coarse rubric; not exact-answer accuracy |
| in-scope answers with >= 1 citation | 1.000 | 7 |  |
| out-of-scope questions refused (no citations or conservative) | 1.000 | 1 |  |
| conservative (non-LLM) answers | 0.000 | 9 |  |
| ids named in answer text that do not exist | 0 | 9 |  |
| response latency p50 / p95 (ms) | 1420 / 9052 | 9 | whole /chat request |
| free-text answer correctness | N/A | 0 | N/A (not scored): no gold answers; only cited-id / keyword expectations are scored |

### G. Web search

| Metric | Live value | n | Note |
|---|---|---|---|
| search executed and returned results | 1.000 | 5 |  |
| mean results per query | 5.000 | 5 |  |
| domain restriction (https + allowlist) | 1.000 | 5 |  |
| all results marked unvetted | 1.000 | 5 |  |
| no catalog id on web results / catalog untouched | 1.000 | 5 |  |
| result relevance (title/url shares a skill keyword) | 0.920 | 5 | keyword heuristic |
| unvetted results excluded from plans | 1.000 | 10 |  |

### H. Vision (known limitation probe)

| Metric | Live value | n | Note |
|---|---|---|---|
| VLM requests for a 2-page image-only PDF | 1 | 1 | 1 == only the first page is read |
| page-1 skill recall (image-only PDF) | 1.000 | 1 |  |
| page-2 skill recall (image-only PDF) | 0.000 | 1 | KNOWN LIMITATION: only the first page is read |

### I. Known-issue probes

| Metric | Live value | n | Note |
|---|---|---|---|
| session cookie forgeable | True | 1 | KNOWN ISSUE (security): unsigned cookie |

### Offline (deterministic, providers disabled) reference values

| Offline metric | Offline value |
|---|---|
| Evidence / skill precision vs gold | 0.9216 |
| Evidence / skill recall vs gold | 0.94 |
| Reflection / correct root-cause node rate | 1.0 |
| Tutor / citation-existence rate | 1.0 |
| Plan / budget utilization at 2/5/10/20 h per week | 38% / 15% / 8% / 4% |

## Cases that did not pass

| Area | Case | Status | Detail |
|---|---|---|---|
| tutor | tutor-gaps_short | provider_error |  |
| tutor | tutor-progress | provider_error |  |
| tutor | tutor-evidence_python | provider_error |  |
| tutor | tutor-resource_backprop | skipped | aborted: provider rate-limited on consecutive cases |
| tutor | tutor-decision_explain | skipped | aborted: provider rate-limited on consecutive cases |
| tutor | tutor-oos_poem | skipped | aborted: provider rate-limited on consecutive cases |
| tutor | tutor-adv_fake_skill | skipped | aborted: provider rate-limited on consecutive cases |
| tutor | tutor-adv_fake_resource | skipped | aborted: provider rate-limited on consecutive cases |

## Human-readable examples

**A. Profiling**

- `profile-data-analyst-tools`: `{"resume": "data-analyst-tools", "expected": ["skill.excel", "skill.powerbi", "skill.sql_aggregation", "skill.sql_fundamentals", "skill.sql_joins", "skill.tableau"], "got": ["skill.excel", "skill.powerbi", "skill.sql_fundamentals", "skill.tableau"], "missed": ["skill.sql_aggregation", "skill.sql_joins"], "extra": [], "sample_claim": ["SQL", "SQL", "skill.sql_fundamentals"]}`

- `profile-ml-engineer-project`: `{"resume": "ml-engineer-project", "expected": ["skill.cnn", "skill.docker", "skill.experiment_tracking", "skill.model_serving", "skill.python", "skill.pytorch", "skill.scikit_learn"], "got": ["skill.docker", "skill.python", "skill.pytorch", "skill.scikit_learn"], "missed": ["skill.cnn", "skill.experiment_tracking", "skill.model_serving"], "extra": [], "sample_claim": ["Python", "Python", "skill.python"]}`

**B. Gap analysis**

- `gap-data-analyst-tools`: `{"resume": "data-analyst-tools", "live_only_gaps": [], "gold_only_gaps": []}`

- `gap-ml-engineer-project`: `{"resume": "ml-engineer-project", "live_only_gaps": [], "gold_only_gaps": []}`

**C. Planner**

- `plan-ml-novice-5h`: `{"persona": "ml-novice-5h", "hours": 5, "utilization": "65/300 min", "degraded(fallback)": false, "validator_rejections": [], "first_items": [["practice", "skill.python", null, 10, 1], ["resource", "skill.cli_basics", "res.fcc_command_line", 45, 2], ["practice", "skill.sql_fundamentals", null, 10, 3]], "reason": "This week focuses on three core skills\u2014Python, command\u2011line usage, and SQL\u2014using concise practice and a short reading, staying within your 270\u2011minute budget."}`

- `plan-ml-claims-8h`: `{"persona": "ml-claims-8h", "hours": 8, "utilization": "75/480 min", "degraded(fallback)": false, "validator_rejections": [], "first_items": [["resource", "skill.cli_basics", "res.fcc_command_line", 45, 1], ["practice", "skill.sql_fundamentals", null, 30, 2]], "reason": "This week focuses on essential tooling: a short command\u2011line intro and hands\u2011on SQL practice, staying within the time budget and skill limits."}`

**D. Assessment**

- `assess-skill.activation_functions`: `{"skill": "skill.activation_functions", "question": "Which activation function is most appropriate for the output layer of a binary classification neural network?", "options": [["Sigmoid", "KEY"], ["ReLU", "misc.relu_always_better"], ["Tanh", null], ["Linear", null]], "explanation": "Sigmoid maps outputs to a probability between 0 and 1.", "blind_solver_agrees": true}`

- `assess-skill.authentication_authorization`: `{"skill": "skill.authentication_authorization", "question": "Which of the following statements about JSON Web Tokens (JWT) is correct?", "options": [["The JWT payload is encrypted, so it can safely contain secret data", "misc.jwt_is_encrypted"], ["The JWT payload is only base64\u2011encoded and signed, making it readable ", "KEY"], ["A JWT must be stored in a secure HTTP\u2011only cookie to be valid", null], ["The JWT signature is optional if the payload is encrypted", null]], "explanation": "A JWT payload is not encrypted; it is merely base64\u2011encoded and signed.", "blind_solver_agrees": true}`

**E. Reflection**

- `reflect-misc.backprop_local_gradient_only`: `{"misconception": "misc.backprop_local_gradient_only", "injected_root": "skill.neural_network_fundamentals", "returned_root": "skill.neural_network_fundamentals", "ops": ["INSERT_REMEDIATION"], "degraded(deterministic policy)": false, "explanation": "We noticed you\u2019re focusing on the local gradient part of back\u2011propagation. To strengthen your understanding, we\u2019ve added a short review of core neural\u2011network fundamentals using two trusted resources, which will help you"}`

- `reflect-misc.big_o_worst_case_only_matters`: `{"misconception": "misc.big_o_worst_case_only_matters", "injected_root": "skill.dsa_sorting_searching", "returned_root": "skill.dsa_sorting_searching", "ops": ["INSERT_REMEDIATION"], "degraded(deterministic policy)": false, "explanation": "We noticed you\u2019re focusing only on worst\u2011case scenarios for Big\u2011O. To strengthen your understanding, we\u2019ve added a concise resource that explains average\u2011case and best\u2011case analyses, helping you apply the right concept t"}`

**F. Tutor**

- `tutor-why_changed_hinted`: `{"q": "Why did my plan change?", "kind": "why_changed", "citations": ["2fae202d-c76b-4f3b-84e4-77d9a9d11926", "a08e201f-2668-4749-a37c-87a73f57a1c9", "skill.chain_rule"], "conservative": false, "first_draft_rejected": false, "answer": "Your plan changed after a reflection triggered by a repeated misconception on backpropagation; the system added a short remediation on the chain_rule skill and a follow\u2011up check, resulting in a new revision of the plan."}`

- `tutor-why_changed_free`: `{"q": "What changed in my plan this week?", "kind": "why_changed", "citations": ["2fae202d-c76b-4f3b-84e4-77d9a9d11926", "bf7964ee-601c-40e8-bcc2-d7f0df0df342"], "conservative": false, "first_draft_rejected": false, "answer": "This week a new revision (revision\u202f2) was applied to your plan. It inserted a short remediation for the skill \u201cchain rule\u201d using the resource \u201cres.khan_diff_calc\u201d and added a follow\u2011up resolution\u2011check probe for that skill."}`

**G. Web search**

- `web-skill.chain_rule`: `{"skill": "skill.chain_rule", "titles": ["Chain rule - Wikipedia", "Chain rule (article) | Taking derivatives | Khan Academy", "Lecture 3: Composite Functions and the Chain Rule | Calculus Revisited"], "domains": ["en.wikipedia.org", "khanacademy.org", "ocw.mit.edu"]}`

- `web-skill.docker`: `{"skill": "skill.docker", "titles": ["Containerization and Orchestration | Coursera", "Containerizing Applications with Docker Compose: Step-by-Step Tutorial", "Containerizing Applications with Docker Compose: Step-by-Step Tutorial"], "domains": ["coursera.org", "geeksforgeeks.org"]}`

**H. Vision (known limitation probe)**

- `vision-first-page-only`: `{"got": ["skill.opencv", "skill.python", "skill.pytorch"], "page1": ["skill.opencv", "skill.python", "skill.pytorch"], "page2": []}`

## LLM calls by schema

| Schema | Tier | Calls | Degraded | Avg latency ms | Retried |
|---|---|---|---|---|---|
| AssessorGeneratedItems | strong | 6 | 0 | 1956 | 0 |
| BlindSolverAnswer | small | 18 | 0 | 810 | 0 |
| ExtractedClaims | mid | 12 | 1 | 3194 | 1 |
| PlannerDraft | mid | 10 | 0 | 9217 | 6 |
| ReflectionResult | strong | 10 | 0 | 2802 | 2 |
| SkillDisambiguation | small | 12 | 0 | 783 | 0 |
| TutorAnswer | strong | 11 | 3 | 2225 | 4 |

