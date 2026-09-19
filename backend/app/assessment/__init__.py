"""Practice & Assessment Engine, Mastery Updater, Struggle Classifier, and
misconception resolution (design §10.4, §18, §19, §20.8;
ARCHITECTURE_CONTRACTS.md §2/§17; already named in §12's package-naming
convention list).

- `mastery.py`: pure Beta-count mastery update (design §10.4). No DB import.
- `struggle.py`: pure, deterministic Struggle Classifier (design §19.2) --
  same "unit-testable with hand-built fixtures" shape as `app/gap/engine.py`,
  `app/retrieval/ranker.py`, `app/planning/validator.py`.
- `grading.py`: MCQ (deterministic) and short-answer (small-LLM, rubric)
  grading.
- `prompting.py`: Assessor Agent prompt/parse (item generation,
  blind-solver validation).
- `item_bank.py`: practice-set assembly (item-bank-first, generate-if-short,
  prerequisite-block rule, design §18.2).
- `resolution.py`: deterministic misconception resolution state machine
  (design §20.8) -- remediation item insertion and verification-probe
  outcome handling. Not the Reflection Agent (design §20's full LLM-driven
  root-cause synthesis and closed operator set remain out of scope, design's
  own next phase).
- `service.py`: async orchestration -- assembling/submitting a practice set,
  end to end (mirrors `app/profiling/onboarding.py`'s "pure algorithm vs.
  DB/gateway glue" split).
"""
