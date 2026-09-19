"""Web fallback Gateway tests (design §14.3 point 6's optional O4 path).
`LLM_PROVIDER=none` (this project's default) means the deterministic degrade
path is what's exercised end to end -- same convention as
`tests/test_langgraph_init.py`'s LLM Gateway coverage.
"""
from __future__ import annotations

import pytest

from app.gateway.web_fallback_gateway import (
    DegradedWebFallbackGateway,
    WebFallbackQuery,
    get_web_fallback_gateway,
)


@pytest.mark.asyncio
async def test_degraded_gateway_returns_no_results_never_fabricates():
    gateway = DegradedWebFallbackGateway()
    response = await gateway.search(WebFallbackQuery(skill_label="Chain Rule", query_text="chain rule calculus"))
    assert response.fetched is False
    assert response.results == []
    assert response.degraded_reason


def test_factory_returns_degraded_gateway_by_default():
    assert isinstance(get_web_fallback_gateway(), DegradedWebFallbackGateway)
