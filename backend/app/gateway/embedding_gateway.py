"""Embedding Gateway.

design §14.1 (retrieval planes must not be mixed), §15.1 (`Resource.embedding`),
§34 ("Managed embedding API or a small local model"), ARCHITECTURE_CONTRACTS.md
§14 (graceful degradation, no LLM/provider key required to run the demo
offline). Mirrors app/gateway/llm_gateway.py's shape: a provider-agnostic
interface with a deterministic, dependency-free fallback used whenever
`LLM_PROVIDER=none` (the default) — so catalog ingestion and resource
embeddings work fully offline without a real provider, and are reproducible
(the same text always yields the same vector).

The fallback is intentionally simple (hashed bag-of-tokens, L2-normalized):
it is not semantically strong, but it is stable, offline, and good enough to
exercise pgvector storage and cosine-distance queries end-to-end. Swapping in
a real provider or local model later only requires filling in the
`NotImplementedError` branch, exactly as the LLM Gateway does.
"""
from __future__ import annotations

import hashlib
import math
import re
from abc import ABC, abstractmethod

from app.db.models import EMBEDDING_DIM

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def deterministic_embedding(text: str, dim: int = EMBEDDING_DIM) -> list[float]:
    """Feature-hashing embedding: each token hashes into one of `dim` buckets
    (sign determined by a second hash, to reduce collision bias), then the
    vector is L2-normalized. Same text -> same vector, always -- required for
    the record/replay-style determinism ARCHITECTURE_CONTRACTS.md §14 asks
    for everywhere else in the stack.
    """
    vec = [0.0] * dim
    tokens = _tokenize(text) or [""]
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        bucket = int.from_bytes(digest[:4], "big") % dim
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vec[bucket] += sign

    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0.0:
        return vec
    return [v / norm for v in vec]


class EmbeddingGateway(ABC):
    @abstractmethod
    async def embed(self, text: str) -> list[float]: ...


class DegradedEmbeddingGateway(EmbeddingGateway):
    """Default gateway when no embedding provider is configured
    (`settings.llm_provider == "none"`, the project default). Deterministic,
    offline, no network call."""

    def __init__(self, dim: int = EMBEDDING_DIM) -> None:
        self.dim = dim

    async def embed(self, text: str) -> list[float]:
        return deterministic_embedding(text, self.dim)


def get_embedding_gateway():
    """Always the deterministic/degraded gateway: no embedding provider is
    implemented in this project, so a configured `LLM_PROVIDER` (which only
    routes the LLM Gateway) must not make this raise -- Phase 12 fixed a crash
    where any provider other than "none" turned intake/upload/planning into a
    500. The degrade is reported honestly by each response's own flags."""
    return DegradedEmbeddingGateway()
