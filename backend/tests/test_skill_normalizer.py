"""Skill Normalizer tests (design §22.1): exact alias -> embedding ->
bounded LLM disambiguation -> unmapped. Embedding and LLM gateways are
stubbed with fully controlled outputs so threshold behavior (which stage
handles a given claim) is deterministic and doesn't depend on the real
hashed-embedding's incidental similarity scores.
"""
from __future__ import annotations

import json

import pytest

from app.db.models import Skill
from app.gateway.embedding_gateway import EmbeddingGateway
from app.gateway.llm_gateway import LLMGateway, LLMResponse
from app.profiling.skill_normalizer import SkillNormalizer
from app.schemas.profiling import ExtractedClaim, SpanOffsets, VerifiedClaim


class StubEmbeddingGateway(EmbeddingGateway):
    def __init__(self, vectors: dict[str, list[float]]) -> None:
        self._vectors = vectors

    async def embed(self, text: str) -> list[float]:
        if text not in self._vectors:
            raise AssertionError(f"StubEmbeddingGateway got an unexpected embed() call: {text!r}")
        return self._vectors[text]


class StubLLMGateway(LLMGateway):
    def __init__(self, response: LLMResponse) -> None:
        self._response = response
        self.calls = 0

    async def complete(self, request):  # noqa: D102 - test double
        self.calls += 1
        return self._response


class UncalledLLMGateway(LLMGateway):
    async def complete(self, request):  # noqa: D102
        raise AssertionError("LLM gateway should not have been called for this case")


def _skill(skill_id: str, label: str, aliases: list[str] | None = None, description: str = "") -> Skill:
    return Skill(skill_id=skill_id, label=label, kind="concept", area="test", aliases=aliases or [], description=description, assessable=True)


def _verified(label: str) -> VerifiedClaim:
    claim = ExtractedClaim(
        label=label,
        category="",
        context_type="skills_list",
        claimed_level_cue=None,
        verbatim_span=label,
        source_doc_id="doc-1",
        span_offsets=SpanOffsets(start=0, end=len(label)),
    )
    return VerifiedClaim(claim=claim, tier="E0", span_verified=True, injection_flagged=False)


# -- exact alias --------------------------------------------------------------


@pytest.mark.asyncio
async def test_exact_label_match():
    skills = [_skill("skill.python", "Python")]
    normalizer = SkillNormalizer(skills, StubEmbeddingGateway({}), UncalledLLMGateway())
    result = await normalizer.normalize(_verified("Python"))
    assert result.skill_id == "skill.python"
    assert result.method == "exact_alias"
    assert result.confidence == 1.0


@pytest.mark.asyncio
async def test_exact_alias_match_case_insensitive():
    skills = [_skill("skill.python", "Python", aliases=["py"])]
    normalizer = SkillNormalizer(skills, StubEmbeddingGateway({}), UncalledLLMGateway())
    result = await normalizer.normalize(_verified("PY"))
    assert result.skill_id == "skill.python"
    assert result.method == "exact_alias"


# -- embedding: confident match skips the LLM ---------------------------------


@pytest.mark.asyncio
async def test_confident_embedding_match_skips_llm():
    skills = [_skill("skill.python", "Python")]
    vectors = {"Python programming": [1.0, 0.0], "Python": [1.0, 0.0]}
    normalizer = SkillNormalizer(skills, StubEmbeddingGateway(vectors), UncalledLLMGateway())
    result = await normalizer.normalize(_verified("Python programming"))
    assert result.skill_id == "skill.python"
    assert result.method == "embedding"
    assert result.confidence >= 0.92


# -- embedding: low score short-circuits straight to unmapped -----------------


@pytest.mark.asyncio
async def test_low_embedding_score_is_unmapped_without_calling_llm():
    skills = [_skill("skill.python", "Python")]
    vectors = {"Quantum knitting": [0.0, 1.0], "Python": [1.0, 0.0]}  # orthogonal -> cosine 0.0
    normalizer = SkillNormalizer(skills, StubEmbeddingGateway(vectors), UncalledLLMGateway())
    result = await normalizer.normalize(_verified("Quantum knitting"))
    assert result.skill_id is None
    assert result.method == "unmapped"


# -- embedding: medium score triggers bounded LLM disambiguation --------------


@pytest.mark.asyncio
async def test_medium_confidence_triggers_llm_disambiguation_and_accepts_pick():
    skills = [_skill("skill.python", "Python"), _skill("skill.pandas", "Pandas")]
    # cos(claim, python) = 0.8 (in [0.55, 0.92) -> ambiguous), cos(claim, pandas) lower.
    vectors = {
        "Python-ish thing": [0.8, 0.6],
        "Python": [1.0, 0.0],
        "Pandas": [0.0, 1.0],
    }
    llm_response = LLMResponse(raw_text=json.dumps({"skill_id": "skill.python"}), parsed=None, degraded=False)
    normalizer = SkillNormalizer(skills, StubEmbeddingGateway(vectors), StubLLMGateway(llm_response))
    result = await normalizer.normalize(_verified("Python-ish thing"))
    assert result.skill_id == "skill.python"
    assert result.method == "llm_disambiguation"


@pytest.mark.asyncio
async def test_medium_confidence_llm_declines_is_unmapped():
    skills = [_skill("skill.python", "Python"), _skill("skill.pandas", "Pandas")]
    vectors = {"Ambiguous thing": [0.8, 0.6], "Python": [1.0, 0.0], "Pandas": [0.0, 1.0]}
    llm_response = LLMResponse(raw_text=json.dumps({"skill_id": None}), parsed=None, degraded=False)
    normalizer = SkillNormalizer(skills, StubEmbeddingGateway(vectors), StubLLMGateway(llm_response))
    result = await normalizer.normalize(_verified("Ambiguous thing"))
    assert result.skill_id is None
    assert result.method == "unmapped"


@pytest.mark.asyncio
async def test_medium_confidence_llm_degraded_is_unmapped():
    skills = [_skill("skill.python", "Python"), _skill("skill.pandas", "Pandas")]
    vectors = {"Ambiguous thing": [0.8, 0.6], "Python": [1.0, 0.0], "Pandas": [0.0, 1.0]}
    llm_response = LLMResponse(raw_text="", parsed=None, degraded=True)
    normalizer = SkillNormalizer(skills, StubEmbeddingGateway(vectors), StubLLMGateway(llm_response))
    result = await normalizer.normalize(_verified("Ambiguous thing"))
    assert result.skill_id is None
    assert result.method == "unmapped"


@pytest.mark.asyncio
async def test_medium_confidence_llm_invents_an_id_is_unmapped():
    # ARCHITECTURE_CONTRACTS.md §7: an LLM must select from the candidate set, never invent an ID.
    skills = [_skill("skill.python", "Python"), _skill("skill.pandas", "Pandas")]
    vectors = {"Ambiguous thing": [0.8, 0.6], "Python": [1.0, 0.0], "Pandas": [0.0, 1.0]}
    llm_response = LLMResponse(raw_text=json.dumps({"skill_id": "skill.made_up"}), parsed=None, degraded=False)
    normalizer = SkillNormalizer(skills, StubEmbeddingGateway(vectors), StubLLMGateway(llm_response))
    result = await normalizer.normalize(_verified("Ambiguous thing"))
    assert result.skill_id is None
    assert result.method == "unmapped"


@pytest.mark.asyncio
async def test_medium_confidence_llm_malformed_json_is_unmapped():
    skills = [_skill("skill.python", "Python"), _skill("skill.pandas", "Pandas")]
    vectors = {"Ambiguous thing": [0.8, 0.6], "Python": [1.0, 0.0], "Pandas": [0.0, 1.0]}
    llm_response = LLMResponse(raw_text="not json", parsed=None, degraded=False)
    normalizer = SkillNormalizer(skills, StubEmbeddingGateway(vectors), StubLLMGateway(llm_response))
    result = await normalizer.normalize(_verified("Ambiguous thing"))
    assert result.skill_id is None
    assert result.method == "unmapped"


@pytest.mark.asyncio
async def test_no_catalog_skills_is_unmapped():
    normalizer = SkillNormalizer([], StubEmbeddingGateway({"X": []}), UncalledLLMGateway())
    result = await normalizer.normalize(_verified("X"))
    assert result.skill_id is None
    assert result.method == "unmapped"
