"""PII scrubbing (design §22.1 pipeline stage 3; §29 "Data privacy": "Contact
PII scrubbed before LLM calls"). Regex-based, best-effort — emails and phone
numbers are reliably pattern-matchable; street addresses are not (no
ML-based NER in scope this phase), so only a conservative heuristic is
applied there and it is documented as best-effort, not a guarantee.

Runs once, before chunking, so every downstream offset (chunks, extracted
claim spans, stored `text_hash`) is relative to the *scrubbed* text — the
raw unscrubbed text is never persisted or sent to an LLM.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
# Phone: optional +country, then groups of digits separated by space/./-, 7-15 digits total.
_PHONE_RE = re.compile(r"(?<!\d)(\+?\d{1,3}[\s.-]?)?(\(?\d{2,4}\)?[\s.-]?){2,5}\d{2,4}(?!\d)")
# Best-effort street address: a leading number followed by 1-4 capitalized words and a
# common street suffix. Deliberately conservative (few false positives) at the cost of recall.
_ADDRESS_RE = re.compile(
    r"\b\d{1,5}\s+([A-Z][a-zA-Z]*\s+){1,4}"
    r"(Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Drive|Dr|Court|Ct|Way|Place|Pl)\b\.?"
)

_REDACTION_TOKEN = {"email": "[REDACTED_EMAIL]", "phone": "[REDACTED_PHONE]", "address": "[REDACTED_ADDRESS]"}


@dataclass
class PiiRedaction:
    kind: str  # email / phone / address
    original: str
    start: int
    end: int


def scrub_pii(text: str) -> tuple[str, list[PiiRedaction]]:
    """Returns `(scrubbed_text, redactions)`. `scrubbed_text` may differ in
    length from `text` (redaction tokens are not the same length as the
    original match), so callers must compute chunk/span offsets against
    `scrubbed_text`, never against the original.
    """
    redactions: list[PiiRedaction] = []

    def _redact(pattern: re.Pattern[str], kind: str, s: str) -> str:
        def _sub(m: re.Match[str]) -> str:
            redactions.append(PiiRedaction(kind=kind, original=m.group(0), start=m.start(), end=m.end()))
            return _REDACTION_TOKEN[kind]

        return pattern.sub(_sub, s)

    scrubbed = _redact(_EMAIL_RE, "email", text)
    scrubbed = _redact(_ADDRESS_RE, "address", scrubbed)
    scrubbed = _redact(_PHONE_RE, "phone", scrubbed)
    return scrubbed, redactions
