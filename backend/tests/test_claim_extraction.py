"""Claim extraction tests: the deterministic fallback extractor (design §30
/ P7's "every LLM-dependent step has a deterministic fallback") and the LLM
response parser (`parse_extraction_response`, schema-validated per
ARCHITECTURE_CONTRACTS.md §6)."""
from __future__ import annotations

import json

import pytest

from app.profiling.claim_extraction import (
    DeterministicClaimExtractor,
    ExtractionParseError,
    SkillPhrase,
    build_extraction_prompt,
    parse_extraction_response,
)


def _extractor() -> DeterministicClaimExtractor:
    return DeterministicClaimExtractor(
        [
            SkillPhrase(phrase="Python", skill_id="skill.python", area="python"),
            SkillPhrase(phrase="SQL", skill_id="skill.sql_fundamentals", area="databases_sql"),
            SkillPhrase(phrase="machine learning", skill_id="skill.ml_intro", area="machine_learning_fundamentals"),
        ]
    )


# -- deterministic extractor --------------------------------------------------


def test_extracts_known_skill_from_skills_list():
    claims = _extractor().extract("Skills: Python, SQL", "doc-1")
    labels = {c.label for c in claims}
    assert labels == {"Python", "SQL"}
    assert all(c.context_type == "skills_list" for c in claims)


def test_extracts_project_context_from_verb_cues():
    text = "Built a data pipeline in Python that loads into a warehouse."
    claims = _extractor().extract(text, "doc-1")
    assert len(claims) == 1
    assert claims[0].context_type == "project"


def test_extracts_experience_context_from_markers():
    text = "Experience with Python in a backend engineering role."
    claims = _extractor().extract(text, "doc-1")
    assert claims[0].context_type == "experience"


def test_infers_level_cue_when_present():
    text = "Advanced Python programmer with 5 years of experience."
    claims = _extractor().extract(text, "doc-1")
    assert claims[0].claimed_level_cue == "advanced"


def test_no_level_cue_when_absent():
    text = "Skills: Python"
    claims = _extractor().extract(text, "doc-1")
    assert claims[0].claimed_level_cue is None


def test_case_insensitive_word_boundary_matching():
    claims = _extractor().extract("worked extensively with python and postgresql", "doc-1")
    assert [c.label for c in claims] == ["python"]  # matched verbatim as it appears


def test_does_not_match_substring_inside_another_word():
    # "SQL" must not match inside "NoSQLDatabase" (no word boundary).
    claims = _extractor().extract("Experience with NoSQLDatabase systems.", "doc-1")
    assert claims == []


def test_multi_word_phrase_matching():
    claims = _extractor().extract("Solid grasp of machine learning fundamentals.", "doc-1")
    assert [c.label for c in claims] == ["machine learning"]


def test_one_claim_per_skill_first_occurrence_only():
    claims = _extractor().extract("Python. More Python. Even more Python.", "doc-1")
    assert len(claims) == 1


def test_unsupported_skill_produces_no_claim():
    # "Rust" is not in the catalog phrase set this extractor was built with.
    claims = _extractor().extract("Experience with Rust and Elixir.", "doc-1")
    assert claims == []


def test_verbatim_span_is_always_a_real_substring_of_the_text():
    text = "Built ML systems using Python and SQL together."
    claims = _extractor().extract(text, "doc-1")
    for c in claims:
        assert text[c.span_offsets.start : c.span_offsets.end] == c.verbatim_span
        assert c.verbatim_span in text


def test_empty_text_yields_no_claims():
    assert _extractor().extract("", "doc-1") == []


def test_extractor_with_no_phrases_yields_no_claims():
    empty_extractor = DeterministicClaimExtractor([])
    assert empty_extractor.extract("Python SQL", "doc-1") == []


# -- LLM prompt / response parsing --------------------------------------------


def test_build_extraction_prompt_includes_document_text_and_id():
    prompt = build_extraction_prompt("Skills: Python", "doc-42")
    assert "doc-42" in prompt
    assert "Skills: Python" in prompt


def test_parse_extraction_response_valid_json():
    payload = [
        {
            "label": "Python",
            "category": "python",
            "context_type": "skills_list",
            "claimed_level_cue": None,
            "verbatim_span": "Python",
            "source_doc_id": "doc-1",
            "span_offsets": {"start": 0, "end": 6},
        }
    ]
    claims = parse_extraction_response(json.dumps(payload), "doc-1")
    assert len(claims) == 1
    assert claims[0].label == "Python"


def test_parse_extraction_response_rejects_malformed_json():
    with pytest.raises(ExtractionParseError):
        parse_extraction_response("not json at all", "doc-1")


def test_parse_extraction_response_rejects_non_array():
    with pytest.raises(ExtractionParseError):
        parse_extraction_response(json.dumps({"label": "Python"}), "doc-1")


def test_parse_extraction_response_rejects_schema_violation():
    payload = [{"label": "Python"}]  # missing required fields
    with pytest.raises(ExtractionParseError):
        parse_extraction_response(json.dumps(payload), "doc-1")


def test_parse_extraction_response_rejects_mismatched_source_doc_id():
    payload = [
        {
            "label": "Python",
            "context_type": "skills_list",
            "verbatim_span": "Python",
            "source_doc_id": "doc-OTHER",
            "span_offsets": {"start": 0, "end": 6},
        }
    ]
    with pytest.raises(ExtractionParseError):
        parse_extraction_response(json.dumps(payload), "doc-1")


def test_parse_extraction_response_fills_in_source_doc_id_when_absent():
    payload = [
        {
            "label": "Python",
            "context_type": "skills_list",
            "verbatim_span": "Python",
            "span_offsets": {"start": 0, "end": 6},
        }
    ]
    claims = parse_extraction_response(json.dumps(payload), "doc-1")
    assert claims[0].source_doc_id == "doc-1"
