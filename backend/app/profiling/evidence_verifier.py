"""Evidence Verifier — deterministic service (design §22.1 stage, §22.4,
§22.5, §22.6). "Never trust the LLM's evidence span blindly": every claim's
`verbatim_span` is checked against the actual source document text before
it can become evidence, tiers are assigned by a fixed rule table (no LLM in
the decision path — ARCHITECTURE_CONTRACTS.md §2 lists this among the
deterministic services), and the prompt-injection detector runs here too, so
a flagged span is caught before normalization/confirmation ever sees it.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

from app.profiling.injection import detect_prompt_injection
from app.schemas.profiling import ExtractedClaim, SpanOffsets, VerifiedClaim

# design §22.5 point 1: "fuzzy-matches it to the source (>= 0.9 similarity after normalization)".
SPAN_SIMILARITY_THRESHOLD = 0.9
INJECTION_WINDOW_CHARS = 200


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def verify_span(claim: ExtractedClaim, source_text: str) -> SpanOffsets | None:
    """Returns the (possibly corrected) offsets the span was actually found
    at, or `None` if it could not be verified at all -- "no span means no
    evidence" (design §22.5 point 2)."""
    span = claim.verbatim_span
    if not span.strip():
        return None

    offsets = claim.span_offsets
    if 0 <= offsets.start < offsets.end <= len(source_text):
        candidate = source_text[offsets.start : offsets.end]
        if _similarity(_normalize_whitespace(candidate), _normalize_whitespace(span)) >= SPAN_SIMILARITY_THRESHOLD:
            return offsets

    # The claimed offsets didn't check out (an LLM can miscount characters) --
    # fall back to a direct case-insensitive search for the span itself.
    idx = source_text.lower().find(span.lower())
    if idx != -1:
        return SpanOffsets(start=idx, end=idx + len(span))
    return None


def check_injection(claim: ExtractedClaim, source_text: str) -> list[str]:
    offsets = claim.span_offsets
    if 0 <= offsets.start <= offsets.end <= len(source_text):
        w_start, w_end = max(0, offsets.start - INJECTION_WINDOW_CHARS), min(len(source_text), offsets.end + INJECTION_WINDOW_CHARS)
        window = source_text[w_start:w_end]
    else:
        window = claim.verbatim_span
    return detect_prompt_injection(window)


def assign_tier(claim: ExtractedClaim, *, is_github_source: bool = False) -> str:
    """design §22.4's deterministic table. `E3` (assessed in-system) is
    never assigned here -- that tier only comes from the Assessor
    (Phase 7, not implemented)."""
    if is_github_source or claim.context_type == "certificate":
        return "E2"
    if claim.context_type in ("project", "experience"):
        return "E1"
    return "E0"  # skills_list, education, or anything else -> the weakest tier


class EvidenceVerifier:
    def verify(self, claim: ExtractedClaim, source_text: str, *, is_github_source: bool = False) -> VerifiedClaim:
        verified_offsets = verify_span(claim, source_text)
        span_verified = verified_offsets is not None
        injection_matches = check_injection(claim, source_text)

        effective_claim = claim
        if verified_offsets is not None and verified_offsets != claim.span_offsets:
            effective_claim = claim.model_copy(update={"span_offsets": verified_offsets})

        return VerifiedClaim(
            claim=effective_claim,
            tier=assign_tier(effective_claim, is_github_source=is_github_source),
            span_verified=span_verified,
            injection_flagged=bool(injection_matches),
            injection_matches=injection_matches,
        )

    def verify_all(
        self, claims: list[ExtractedClaim], source_text: str, *, is_github_source: bool = False
    ) -> list[VerifiedClaim]:
        return [self.verify(c, source_text, is_github_source=is_github_source) for c in claims]
