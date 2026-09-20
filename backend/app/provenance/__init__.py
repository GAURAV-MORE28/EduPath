"""Provenance Service (design §24, §14.5; ARCHITECTURE_CONTRACTS.md §2/§13,
"Provenance / 'Why?' for every decision"): a deterministic service, not an
LLM agent. Its two jobs per the design's role table (§8.1, row 331):
"Create/resolve `DecisionRecord`s; verify citations in tutor answers."

`DecisionRecord` creation already exists (`app/reflection/repository.py`'s
`create_decision_record`, Phase 9 -- Reflection is the first real writer).
This package adds the second half: `citations.py`'s `verify_citations`, the
deterministic check behind design §14.5's "[Tutor/Planner] may reference only
IDs present in their context... the Provenance Service verifies that every
cited ID exists."
"""
