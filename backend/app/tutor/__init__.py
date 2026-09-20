"""Tutor Agent package (design §8.2's A5, §23; ARCHITECTURE_CONTRACTS.md §2).

The fifth and last LLM agent: a read-only, tool-calling, citation-verified
natural-language interface over the learner's own structured state and the
curated graph. It never mutates persisted state -- `commit_*` tools are not
in its inventory (ARCHITECTURE_CONTRACTS.md §13) -- and every factual claim
in its answer must resolve to an ID this turn's own tool calls actually
surfaced (`app/provenance/citations.py`).

`tools.py` (the read-only tool inventory), `intent.py` (rule-based
`classify_intent`/`plan_tools`, design §9.6/§23.2), `prompting.py`
(`compose_answer`'s prompt/parse), `conservative.py` (the deterministic,
LLM-free fallback answer), `report_builder.py` (the deterministic Report
Builder, design §25.2's `ProgressReport` -- a separate deliverable of this
phase, not itself a tool the Tutor Agent calls, though `get_progress`
wraps it), and `service.py` (async orchestration -- builds the per-turn
`TutorContext`, runs the G4 graph)."""
