"""Skill Normalizer — deterministic service, with one small-LLM step for
ambiguous cases only (ARCHITECTURE_CONTRACTS.md §2 footnote: "Skill
Normalizer uses a small LLM only for ambiguous-alias disambiguation; it is
not counted among the 5 agents"). Pipeline (design §22.1): exact alias match
-> embedding match -> bounded LLM disambiguation among the top-5 candidates
-> `unmapped`.

An unmapped label is retained as free text, never force-fit onto a graph
node (design §22.5 point 4) — this module returns `skill_id=None` rather
than guessing when it isn't confident, at every stage.
"""
from __future__ import annotations

import json

from pydantic import BaseModel

from app.db.models import Skill
from app.gateway.embedding_gateway import EmbeddingGateway
from app.gateway.llm_gateway import LLMGateway, LLMRequest, ModelTier
from app.schemas.profiling import NormalizedClaim, VerifiedClaim

# Tunable defaults (ARCHITECTURE_CONTRACTS.md §14: kept in one place, not scattered).
EMBEDDING_CONFIDENT_THRESHOLD = 0.92  # accept the top embedding match outright, skip the LLM call
EMBEDDING_MIN_CANDIDATE_THRESHOLD = 0.55  # below this, not even worth asking the LLM to pick among candidates
TOP_K_CANDIDATES = 5

DISAMBIGUATION_SYSTEM_PROMPT = (
    "You match a free-text skill label to the single best-fitting catalog skill ID from a "
    "fixed candidate list, or say none of them fit. You may ONLY answer with one of the given "
    "IDs or the literal string \"none\" — never invent an ID. Output strict JSON: "
    '{"skill_id": "<one of the given ids>" | null}.'
)


class _DisambiguationResponse(BaseModel):
    skill_id: str | None


class DisambiguationParseError(ValueError):
    pass


def build_disambiguation_prompt(label: str, candidates: dict[str, Skill]) -> str:
    lines = [f"Free-text skill label: {label!r}", "Candidates:"]
    for skill_id, skill in candidates.items():
        lines.append(f"- id={skill_id} label={skill.label!r} description={skill.description!r}")
    return "\n".join(lines)


def parse_disambiguation_response(raw_text: str, valid_ids: set[str]) -> str | None:
    try:
        payload = json.loads(raw_text)
        parsed = _DisambiguationResponse.model_validate(payload)
    except Exception as exc:  # noqa: BLE001 - any parse/validation failure is treated uniformly
        raise DisambiguationParseError(str(exc)) from exc

    if parsed.skill_id is None:
        return None
    if parsed.skill_id not in valid_ids:
        # ARCHITECTURE_CONTRACTS.md §7: "an LLM never invents an ID; it selects from a
        # pre-built candidate ID set" -- an out-of-set answer is a validation failure, not a pick.
        raise DisambiguationParseError(f"skill_id {parsed.skill_id!r} is not among the offered candidates")
    return parsed.skill_id


def _cosine(a: list[float], b: list[float]) -> float:
    # Both vectors are L2-normalized by EmbeddingGateway, so dot product == cosine similarity.
    return sum(x * y for x, y in zip(a, b))


class SkillNormalizer:
    def __init__(self, skills: list[Skill], embedding_gateway: EmbeddingGateway, llm_gateway: LLMGateway) -> None:
        self._skills_by_id = {s.skill_id: s for s in skills}
        self._exact_index: dict[str, str] = {}
        for s in skills:
            for phrase in (s.label, *s.aliases):
                key = phrase.strip().lower()
                if key:
                    self._exact_index.setdefault(key, s.skill_id)
        self._embedding_gateway = embedding_gateway
        self._llm_gateway = llm_gateway
        self._skill_embedding_cache: dict[str, list[float]] | None = None

    async def normalize(self, verified: VerifiedClaim) -> NormalizedClaim:
        label = verified.claim.label.strip()

        exact_id = self._exact_index.get(label.lower())
        if exact_id is not None:
            return NormalizedClaim(verified=verified, skill_id=exact_id, method="exact_alias", confidence=1.0)

        candidates = await self._top_candidates(label)
        if not candidates:
            return NormalizedClaim(verified=verified, skill_id=None, method="unmapped", confidence=0.0)

        top_id, top_score = candidates[0]
        if top_score >= EMBEDDING_CONFIDENT_THRESHOLD:
            return NormalizedClaim(verified=verified, skill_id=top_id, method="embedding", confidence=top_score)
        if top_score < EMBEDDING_MIN_CANDIDATE_THRESHOLD:
            return NormalizedClaim(verified=verified, skill_id=None, method="unmapped", confidence=top_score)

        picked = await self._disambiguate(label, candidates)
        if picked is not None:
            picked_id, picked_score = picked
            return NormalizedClaim(verified=verified, skill_id=picked_id, method="llm_disambiguation", confidence=picked_score)

        # LLM unavailable or declined/failed to pick among a merely-plausible set of
        # candidates -> do not force-fit a medium-confidence guess; leave unmapped.
        return NormalizedClaim(verified=verified, skill_id=None, method="unmapped", confidence=top_score)

    async def _skill_embeddings(self) -> dict[str, list[float]]:
        if self._skill_embedding_cache is None:
            cache: dict[str, list[float]] = {}
            for skill_id, skill in self._skills_by_id.items():
                text = f"{skill.label}. {skill.description}" if skill.description else skill.label
                cache[skill_id] = await self._embedding_gateway.embed(text)
            self._skill_embedding_cache = cache
        return self._skill_embedding_cache

    async def _top_candidates(self, label: str) -> list[tuple[str, float]]:
        label_vec = await self._embedding_gateway.embed(label)
        skill_vecs = await self._skill_embeddings()
        scored = [(skill_id, _cosine(label_vec, vec)) for skill_id, vec in skill_vecs.items()]
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[:TOP_K_CANDIDATES]

    async def _disambiguate(self, label: str, candidates: list[tuple[str, float]]) -> tuple[str, float] | None:
        candidate_skills = {sid: self._skills_by_id[sid] for sid, _ in candidates}
        request = LLMRequest(
            tier=ModelTier.SMALL,  # design §33.2: normalization disambiguation is a small/fast-tier task
            system_prompt=DISAMBIGUATION_SYSTEM_PROMPT,
            user_prompt=build_disambiguation_prompt(label, candidate_skills),
            schema_name="SkillDisambiguation",
        )
        response = await self._llm_gateway.complete(request)
        if response.degraded:
            return None
        try:
            picked_id = parse_disambiguation_response(response.raw_text, valid_ids=set(candidate_skills))
        except DisambiguationParseError:
            # "Bounded": one attempt, no retry loop here -- a malformed disambiguation
            # answer just means this claim falls through to unmapped, not a hang.
            return None
        if picked_id is None:
            return None
        return picked_id, dict(candidates)[picked_id]
