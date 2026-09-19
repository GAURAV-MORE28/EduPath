"""Learner Profiling + Evidence Pipeline (design §10, §22; ARCHITECTURE_CONTRACTS.md
§12's package-naming convention: `profiling/`). Deterministic services only —
`ProfilerAgent` (the one LLM agent in this pipeline) lives in `app/agents/profiler.py`
per the project's existing one-file-per-agent convention; everything here is
called *by* that agent's orchestrator node or by the confirm-claims API route,
never the other way around.
"""
