"""LangGraph initialization test: the orchestration framework compiles and
runs a trivial graph end to end (no business logic — see graphs.py)."""
import pytest

from app.orchestration.graphs import build_bootstrap_graph


def test_bootstrap_graph_compiles() -> None:
    graph = build_bootstrap_graph()
    assert graph is not None


@pytest.mark.asyncio
async def test_bootstrap_graph_runs_to_completion() -> None:
    graph = build_bootstrap_graph()
    result = await graph.ainvoke({"run_id": "test-run", "learner_id": "u1"})
    assert result["status"] == "completed"
