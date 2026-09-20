"""`app/provenance/citations.py::verify_citations` — pure, DB/LLM-free."""
from __future__ import annotations

from app.provenance.citations import verify_citations


def test_all_cited_ids_valid_passes():
    result = verify_citations(["skill.a", "ev_1"], {"skill.a", "ev_1", "skill.b"})
    assert result.passed
    assert result.invalid_ids == []
    assert result.cited_ids == ["skill.a", "ev_1"]


def test_unknown_cited_id_fails():
    result = verify_citations(["skill.a", "skill.invented"], {"skill.a"})
    assert not result.passed
    assert result.invalid_ids == ["skill.invented"]


def test_no_citations_fails():
    result = verify_citations([], {"skill.a"})
    assert not result.passed
    assert result.reason == "no citations"


def test_duplicate_citations_deduplicated():
    result = verify_citations(["skill.a", "skill.a"], {"skill.a"})
    assert result.passed
    assert result.cited_ids == ["skill.a"]


def test_partial_invalid_lists_every_invalid_id():
    result = verify_citations(["skill.a", "skill.b", "skill.c"], {"skill.a"})
    assert not result.passed
    assert result.invalid_ids == ["skill.b", "skill.c"]
