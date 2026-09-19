"""Skill-Gap Engine package (design §13; ARCHITECTURE_CONTRACTS.md §4/§12
naming convention: `gap/`).

Deterministic diff of the target-role subgraph (`app/graph/queries.py`,
Phase 3) against a learner's evidence-graded skill state (`LearnerSkillState`
/ `Evidence`, Phase 2). **No LLM in the decision path**
(ARCHITECTURE_CONTRACTS.md §4: "100% deterministic... an LLM may only
narrate the result afterward") — this package contains no gateway/agent
imports, by design.
"""
