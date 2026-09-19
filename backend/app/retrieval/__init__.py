"""Resource Retriever/Ranker package (design §14.3, §15; ARCHITECTURE_CONTRACTS.md
§2: "Resource Retriever/Ranker... deterministic service"). Not one of design
§35's named packages (`profiling/`, `graph/`, `gap/`, `planning/`,
`assessment/`, `reflection/`, `tutor/`, `provenance/`, `gateway/`) — an
addition, same latitude Phase 3 already used for `catalog/`.

`ranker.py` is the pure, deterministic core (graph-anchored eligibility
filter -> hybrid dense+keyword retrieval -> RRF fusion -> weighted ranking ->
MMR diversification), unit-testable with hand-built fixtures and no DB/LLM
involved (design §14.1: "Prerequisite reasoning must not depend on embedding
similarity" -- and neither does anything else here depend on an LLM: dense
relevance uses the existing `EmbeddingGateway`, never an LLM call).
`service.py` is the thin async orchestration layer that fetches real catalog
rows and calls into it. **No LLM anywhere in this package** -- resources are
never invented; every recommendation references an existing `resource_id`
from the curated catalog (design §15.2).
"""
