"""Planning Engine (design §16-§17; ARCHITECTURE_CONTRACTS.md §10).

Package-per-responsibility (`ARCHITECTURE_CONTRACTS.md` §12 already names
`planning/` in the convention list, alongside `profiling/`, `gap/`, etc.).

- `candidates.py`: orchestration glue -- turns the Gap Engine's
  `LearningObjective[]` (Phase 4) into per-objective resource/practice
  candidate sets via the Resource Retriever/Ranker (Phase 6).
- `prompting.py`: the Planner Agent's prompt/parse logic (candidate-ID-only
  output, ARCHITECTURE_CONTRACTS.md §7).
- `validator.py`: the deterministic Plan Validator (V1-V10, design §17.2).
  A pure function -- no DB/gateway import -- same "unit-testable with
  hand-built fixtures" shape as `app/gap/engine.py` and
  `app/retrieval/ranker.py`.
- `fallback.py`: the deterministic Fallback Planner (design §16.4). Also
  pure.
- `service.py`: async orchestration -- builds candidates, runs the G2
  Planning graph, and persists the result (`WeeklyPlan`/`PlanRevision`/
  `PlanItem`). Mirrors `app/profiling/onboarding.py`'s split between "pure
  algorithm" and "DB/gateway glue".
"""
