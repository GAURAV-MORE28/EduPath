"""Skill Graph Service (design §35's `graph/` package; ARCHITECTURE_CONTRACTS.md
§5). Deterministic — no LLM in this package. Owns curated-graph loading
(Postgres -> NetworkX), structural validation, and read-only traversal
queries (ancestors/descendants, topological order, role subgraphs,
prerequisite-path explanation). Does not compute learner-specific gaps —
that is the Gap Engine (`app/gap/`, Phase 4, not implemented yet).
"""
