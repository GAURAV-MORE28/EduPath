"""EmbeddingGateway tests (app/gateway/embedding_gateway.py): the
degraded/deterministic fallback used when no embedding provider is
configured (ARCHITECTURE_CONTRACTS.md §14 — offline determinism)."""
from __future__ import annotations

import math

import pytest

from app.gateway.embedding_gateway import DegradedEmbeddingGateway, deterministic_embedding, get_embedding_gateway


def test_same_text_yields_same_vector() -> None:
    a = deterministic_embedding("chain rule differentiation")
    b = deterministic_embedding("chain rule differentiation")
    assert a == b


def test_different_text_yields_different_vector() -> None:
    a = deterministic_embedding("chain rule differentiation")
    b = deterministic_embedding("SQL joins and normalization")
    assert a != b


def test_vector_is_l2_normalized() -> None:
    vec = deterministic_embedding("backpropagation and gradient descent")
    norm = math.sqrt(sum(v * v for v in vec))
    assert math.isclose(norm, 1.0, abs_tol=1e-9)


def test_dimension_matches_requested_dim() -> None:
    assert len(deterministic_embedding("x", dim=64)) == 64
    assert len(deterministic_embedding("x", dim=256)) == 256


def test_empty_text_does_not_raise() -> None:
    vec = deterministic_embedding("")
    assert len(vec) == 256


@pytest.mark.asyncio
async def test_degraded_gateway_embed() -> None:
    gateway = DegradedEmbeddingGateway(dim=32)
    vec = await gateway.embed("resource about neural networks")
    assert len(vec) == 32


def test_get_embedding_gateway_defaults_to_degraded(monkeypatch) -> None:
    from app import config

    config.get_settings.cache_clear()
    monkeypatch.setenv("LLM_PROVIDER", "none")
    gateway = get_embedding_gateway()
    assert isinstance(gateway, DegradedEmbeddingGateway)
    config.get_settings.cache_clear()
