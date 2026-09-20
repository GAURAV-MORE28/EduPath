"""Embedding Gateway.

design §14.1 (retrieval planes must not be mixed), §15.1 (`Resource.embedding`),
§34 ("Managed embedding API or a small local model"), ARCHITECTURE_CONTRACTS.md
§14 (graceful degradation, no provider key required to run the demo offline).

Two implementations behind one interface:

* `DegradedEmbeddingGateway` -- deterministic hashed bag-of-tokens (L2-normalized): not semantically
  strong, but stable, offline and reproducible. The default (`EMBEDDING_PROVIDER=none`).
* `HuggingFaceEmbeddingGateway` -- Qwen3-Embedding through the Hugging Face router
  (`EMBEDDING_PROVIDER=huggingface`, needs `HF_TOKEN`).

**Catalog and query vectors must come from the same provider.** After changing `EMBEDDING_PROVIDER`
re-embed the stored catalog: `python scripts/reembed_catalog.py`.
"""
from __future__ import annotations

import asyncio
import hashlib
import math
import re
from abc import ABC, abstractmethod
from collections import OrderedDict

import httpx

from app.config import get_settings
from app.db.models import EMBEDDING_DIM
from app.logging_config import get_logger

logger = get_logger(__name__)

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

    async def embed_many(self, texts: list[str]) -> list[list[float]]:
        """Default: one call per text. Remote gateways override this to batch."""
        return [await self.embed(t) for t in texts]


class DegradedEmbeddingGateway(EmbeddingGateway):
    """Deterministic, offline, no network call: the default (`EMBEDDING_PROVIDER=none`) and the
    fallback whenever a remote embedding call fails."""

    def __init__(self, dim: int = EMBEDDING_DIM) -> None:
        self.dim = dim

    async def embed(self, text: str) -> list[float]:
        return deterministic_embedding(text, self.dim)


def _truncate_and_normalize(vector: list[float], dim: int) -> list[float]:
    """Qwen3-Embedding is trained with Matryoshka representation learning: the first `dim` coordinates
    are themselves a valid (lower-dimensional) embedding once re-normalized. This keeps the existing
    `vector(256)` column, so switching providers needs no schema migration."""
    v = vector[:dim]
    norm = math.sqrt(sum(x * x for x in v))
    return [x / norm for x in v] if norm else v


class HuggingFaceEmbeddingGateway(EmbeddingGateway):
    """Qwen3-Embedding via the Hugging Face router (served by the `deepinfra` provider, OpenAI-style
    `/embeddings`). Batched, cached in-process (skill labels and queries repeat constantly), bounded
    retries, and a *logged* fallback to the deterministic embedding if the service is unreachable.

    The fallback matters: catalog vectors stored in Postgres come from this provider, so a deterministic
    query vector is not comparable to them -- dense relevance degrades to noise for that call (the keyword
    half of the hybrid retrieval and the graph-anchored eligibility still hold). Better a weaker
    ranking than a failed request."""

    BATCH_SIZE = 64
    CACHE_SIZE = 8192

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str,
        dim: int = EMBEDDING_DIM,
        timeout_s: float = 30.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key, self._model, self._url = api_key, model, f"{base_url.rstrip('/')}/embeddings"
        self._dim, self._timeout_s, self._client = dim, timeout_s, client
        self._cache: OrderedDict[str, list[float]] = OrderedDict()
        self._fallback = DegradedEmbeddingGateway(dim)

    async def embed(self, text: str) -> list[float]:
        return (await self.embed_many([text]))[0]

    async def embed_many(self, texts: list[str]) -> list[list[float]]:
        missing = list(dict.fromkeys(t for t in texts if t not in self._cache))
        fetched: dict[str, list[float]] = {}
        for start in range(0, len(missing), self.BATCH_SIZE):
            batch = missing[start : start + self.BATCH_SIZE]
            vectors, real = await self._request(batch)
            for text, vec in zip(batch, vectors):
                fetched[text] = vec
                if real:  # never cache a deterministic stand-in as if it were a real embedding
                    self._cache[text] = vec
                    if len(self._cache) > self.CACHE_SIZE:
                        self._cache.popitem(last=False)
        return [self._cache[t] if t in self._cache else fetched[t] for t in texts]

    async def _request(self, batch: list[str]) -> tuple[list[list[float]], bool]:
        last = ""
        for attempt in range(3):
            try:
                http = self._client or httpx.AsyncClient(timeout=self._timeout_s)
                try:
                    resp = await http.post(
                        self._url, json={"model": self._model, "input": batch}, headers={"Authorization": f"Bearer {self._api_key}"}
                    )
                finally:
                    if self._client is None:
                        await http.aclose()
                if resp.status_code == 200:
                    data = sorted(resp.json()["data"], key=lambda d: d["index"])
                    if len(data) == len(batch):
                        return [_truncate_and_normalize(d["embedding"], self._dim) for d in data], True
                    last = "embedding count mismatch"
                else:
                    last = f"status {resp.status_code}"
                    if resp.status_code < 500 and resp.status_code not in (408, 429):
                        break  # a 4xx (bad key, unknown model) will not get better by retrying
            except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
                last = type(exc).__name__
            await asyncio.sleep(0.5 * (2**attempt))
        logger.warning("edupath.embedding.remote_failed_using_deterministic_fallback", reason=last, batch=len(batch))
        return [await self._fallback.embed(t) for t in batch], False


_gateway_singleton: EmbeddingGateway | None = None


def get_embedding_gateway() -> EmbeddingGateway:
    """`EMBEDDING_PROVIDER=huggingface` (and an `HF_TOKEN`) -> Qwen3-Embedding; anything else -> the
    deterministic gateway. One process-wide instance so the cache is shared across requests."""
    global _gateway_singleton
    settings = get_settings()
    if settings.embedding_provider == "huggingface" and settings.hf_token:
        if not isinstance(_gateway_singleton, HuggingFaceEmbeddingGateway):
            _gateway_singleton = HuggingFaceEmbeddingGateway(
                api_key=settings.hf_token, model=settings.embedding_model, base_url=settings.embedding_base_url
            )
        return _gateway_singleton
    return DegradedEmbeddingGateway()
