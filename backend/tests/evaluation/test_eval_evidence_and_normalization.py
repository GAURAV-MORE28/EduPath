"""Evaluation: evidence correctness and skill normalization (design §32.2 rows 1-2).

Evidence correctness -- "% of claims whose span actually supports the skill" -- is measured over a
gold set of resumes pushed through the real upload endpoint (Profiler -> Evidence Verifier ->
Skill Normalizer). Normalization is top-1 accuracy of `skill_id` mapping over a labelled label set,
plus the design's hard rule that an unrecognisable label stays *unmapped* (never force-fit).
"""
from __future__ import annotations

import pytest

from app.gateway.embedding_gateway import DegradedEmbeddingGateway
from app.gateway.llm_gateway import LLMGateway
from app.profiling.pii import scrub_pii
from app.profiling.skill_normalizer import SkillNormalizer
from app.repositories.catalog_repository import CatalogRepository
from app.schemas.profiling import ExtractedClaim, SpanOffsets, VerifiedClaim
from tests.evaluation.metrics import load_gold, record

pytestmark = pytest.mark.asyncio

INTAKE = {"current_skills": [], "experience_summary": "", "target_role_id": "role.ml_engineer", "career_goal": "", "weekly_hours": 6}


async def _skills_by_id() -> dict:
    from app.db.session import SessionLocal

    async with SessionLocal() as session:
        return {s.skill_id: s for s in await CatalogRepository(session).get_all_skills()}


def _supports(span: str, skill) -> bool:
    """A span supports a skill when it literally contains the skill's label or one of its aliases."""
    low = span.lower()
    return any(p.strip().lower() in low for p in (skill.label, *skill.aliases) if p.strip())


async def test_evidence_correctness_over_the_gold_resume_set(app_client):
    skills = await _skills_by_id()
    resumes = load_gold("resumes.json")
    total_claims = supported = offsets_ok = raw_offsets_ok = 0
    tp = fp = fn = 0
    forbidden_hits: list[str] = []
    missed: list[str] = []
    tiers_seen: set[str] = set()

    for resume in resumes:
        app_client.cookies.set("session", f"eval-{resume['id']}")
        assert (await app_client.post("/api/learners", json=INTAKE)).status_code == 201
        resp = await app_client.post(
            "/api/learners/me/documents", files={"file": (f"{resume['id']}.md", resume["text"].encode(), "text/markdown")}
        )
        assert resp.status_code == 200, resume["id"]
        claims = (await app_client.get("/api/learners/me/claims/pending")).json()
        got_skills = {c["normalized_skill_id"] for c in claims if c["normalized_skill_id"]}

        for claim in claims:
            total_claims += 1
            tiers_seen.add(claim["tier"])
            start, end = claim["span_offsets"]["start"], claim["span_offsets"]["end"]
            # offsets index the PII-scrubbed text the Profiler actually reads (app/profiling/pii.py's contract)
            scrubbed = scrub_pii(resume["text"])[0]
            offsets_ok += scrubbed[start:end] == claim["verbatim_span"]
            raw_offsets_ok += resume["text"][start:end] == claim["verbatim_span"]
            if claim["normalized_skill_id"]:
                supported += _supports(claim["verbatim_span"], skills[claim["normalized_skill_id"]])
            else:
                supported += 1  # an unmapped claim asserts no skill, so it cannot be an unsupported one

        expected = set(resume["expected"])
        tp += len(got_skills & expected)
        fp += len(got_skills - expected)
        fn += len(expected - got_skills)
        forbidden_hits += [f"{resume['id']}:{s}" for s in got_skills & set(resume["forbidden"])]
        missed += [f"{resume['id']}:{s}" for s in expected - got_skills]

    correctness = supported / total_claims
    span_fidelity = offsets_ok / total_claims
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    record("Evidence", "evidence correctness (span supports skill)", correctness, ">= 0.95", f"{total_claims} claims / {len(resumes)} resumes")
    record("Evidence", "verbatim-span fidelity", span_fidelity, "1.00", "scrubbed_text[start:end] == verbatim_span")
    record("Evidence", "span offsets valid against the raw (unscrubbed) text", raw_offsets_ok / total_claims, "report",
           "< 1.0 only for documents containing contact PII: offsets index the PII-scrubbed text (known limitation)")
    record("Evidence", "skill precision vs gold", precision, "report")
    record("Evidence", "skill recall vs gold", recall, "report", f"missed: {missed}" if missed else "")
    record("Evidence", "forbidden-skill hits (injection / negatives)", len(forbidden_hits), "0", ", ".join(forbidden_hits))

    assert correctness >= 0.95
    assert span_fidelity == 1.0
    assert not forbidden_hits, forbidden_hits
    assert precision >= 0.9, f"precision {precision:.2f}"
    assert recall >= 0.8, f"recall {recall:.2f}; missed {missed}"
    assert tiers_seen <= {"E0", "E1"}, "a resume alone can never mint E2/E3 evidence"


async def test_no_claim_survives_without_a_verbatim_span_in_the_document(app_client):
    """The verifier's job: a claim whose span is not literally in the source never becomes evidence."""
    from app.profiling.evidence_verifier import EvidenceVerifier

    text = "Skills: Python and Docker."
    fabricated = ExtractedClaim(
        label="Kubernetes", category="", context_type="skills_list", claimed_level_cue="expert",
        verbatim_span="expert in Kubernetes", source_doc_id="d1", span_offsets=SpanOffsets(start=0, end=20),
    )
    genuine = ExtractedClaim(
        label="Python", category="", context_type="skills_list", claimed_level_cue=None,
        verbatim_span="Python", source_doc_id="d1", span_offsets=SpanOffsets(start=8, end=14),
    )
    verified = {v.claim.label: v for v in EvidenceVerifier().verify_all([fabricated, genuine], text)}
    assert verified["Python"].span_verified is True
    assert verified["Kubernetes"].span_verified is False  # unverified claims are dropped by the pipeline, never committed
    record("Evidence", "fabricated claims rejected by span verification", 1.0, "1.00", "1/1")


async def test_skill_normalization_top1_accuracy_and_unmapped_discipline(catalog_session):
    skills = await CatalogRepository(catalog_session).get_all_skills()
    normalizer = SkillNormalizer(skills, DegradedEmbeddingGateway(), LLMGateway())
    gold = load_gold("normalization.json")

    by_kind: dict[str, list[bool]] = {}
    wrong: list[str] = []
    for case in gold:
        claim = ExtractedClaim(
            label=case["label"], category="", context_type="skills_list", claimed_level_cue=None,
            verbatim_span=case["label"], source_doc_id="d", span_offsets=SpanOffsets(start=0, end=len(case["label"])),
        )
        result = await normalizer.normalize(VerifiedClaim(claim=claim, tier="E1", span_verified=True, injection_flagged=False))
        ok = result.skill_id == case["expected"]
        by_kind.setdefault(case["kind"], []).append(ok)
        if not ok:
            wrong.append(f"{case['label']!r} -> {result.skill_id} ({result.method}), expected {case['expected']}")

    mappable = [ok for kind, oks in by_kind.items() if kind != "unmappable" for ok in oks]
    top1 = sum(mappable) / len(mappable)
    unmapped = by_kind["unmappable"]
    unmapped_rate = sum(unmapped) / len(unmapped)
    record("Normalization", "top-1 accuracy (mappable labels)", top1, ">= 0.95", f"{len(mappable)} labels")
    record("Normalization", "alias/variant accuracy", sum(by_kind["alias"] + by_kind["variant"]) / len(by_kind["alias"] + by_kind["variant"]), "1.00")
    record("Normalization", "unmappable labels left unmapped", unmapped_rate, "1.00", f"{len(unmapped)} labels; force-fit = a hallucinated skill")
    if wrong:
        print("NORMALIZATION-MISSES:", wrong)
    assert unmapped_rate == 1.0, wrong  # never force-fit a graph node (design §22.5 point 4)
    assert top1 >= 0.95, wrong
