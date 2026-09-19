"""LangGraph orchestration skeleton.

Design §9.1: four graphs (G1 Onboarding, G2 Planning, G3 Evidence-Response,
G4 Tutor), each an explicit LangGraph state machine — never a free-form
agent loop (ARCHITECTURE_CONTRACTS.md: "Explicit state over emergent
behavior"). Phase 1 builds the orchestration framework and a trivial
`bootstrap` graph used only to prove LangGraph compiles and runs in this
process; G1-G4's real nodes are built by the phases that own them (2, 5, 8, 9).
"""
from __future__ import annotations

from typing import Any

from langgraph.graph import END, StateGraph

from app.orchestration.state import RunState


async def _start_node(state: RunState) -> dict[str, Any]:
    return {"status": "running"}


async def _finish_node(state: RunState) -> dict[str, Any]:
    return {"status": "completed"}


def build_bootstrap_graph():
    """A minimal two-node graph with no business logic, used by the startup
    health check and the LangGraph initialization test to prove the
    orchestration framework (state schema, compilation, execution) works."""
    graph = StateGraph(RunState)
    graph.add_node("start", _start_node)
    graph.add_node("finish", _finish_node)
    graph.set_entry_point("start")
    graph.add_edge("start", "finish")
    graph.add_edge("finish", END)
    return graph.compile()


def build_onboarding_graph():
    """G1 Onboarding — placeholder. Implemented in Phase 2."""
    raise NotImplementedError("G1 Onboarding graph is implemented in Phase 2 (Learner profiling).")


def build_planning_graph():
    """G2 Planning — placeholder. Implemented in Phase 5."""
    raise NotImplementedError("G2 Planning graph is implemented in Phase 5 (Planner).")


def build_evidence_response_graph():
    """G3 Evidence-Response — placeholder. Implemented in Phase 8."""
    raise NotImplementedError("G3 Evidence-Response graph is implemented in Phase 8 (Reflection / re-planning).")


def build_tutor_graph():
    """G4 Tutor — placeholder. Implemented in Phase 9."""
    raise NotImplementedError("G4 Tutor graph is implemented in Phase 9 (Tutor).")
