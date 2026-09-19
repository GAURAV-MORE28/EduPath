"""Prompt-injection detection (design §22.6, §29 "Prompt injection in
documents"). Documents are untrusted data (Trust Zone T1,
ARCHITECTURE_CONTRACTS.md §13/design §26.3); the Profiler has no side-effect
tools regardless, but an injected instruction could still try to talk the
model into fabricating skills/levels it wasn't asked to report. This module
is the code-side backstop design §22.6 requires: "instruction-like patterns
... are flagged and reported, and the flagged spans are not used as
evidence" — independent of whatever the LLM itself does with the text.

Pattern-based, not a classifier: false negatives are expected (this is not a
complete injection defense — see `docs/EduPath_System_Design.md`'s security
section for the fuller defense-in-depth story: no side-effect tools,
schema-only output, span verification). This module's job is narrow: catch
the obvious cases and make sure a flagged span never becomes evidence.
"""
from __future__ import annotations

import re

_INJECTION_PATTERNS = [
    re.compile(r"ignore (all |the )?(previous|prior|above) (instructions?|prompts?)", re.IGNORECASE),
    re.compile(r"disregard (all |the )?(previous|prior|above)", re.IGNORECASE),
    re.compile(r"you are now\b", re.IGNORECASE),
    re.compile(r"new instructions?:", re.IGNORECASE),
    re.compile(r"system\s*:\s*", re.IGNORECASE),
    re.compile(r"\bact as (a|an)\b", re.IGNORECASE),
    re.compile(r"give me all (skills|claims|evidence)", re.IGNORECASE),
    re.compile(r"mark (me|this) as (an? )?(expert|proficient|master)", re.IGNORECASE),
    re.compile(r"do not (verify|check|flag)", re.IGNORECASE),
    re.compile(r"\[\s*system\s*\]", re.IGNORECASE),
]


def detect_prompt_injection(text: str) -> list[str]:
    """Returns the list of matched injection phrases (empty if none)."""
    matches: list[str] = []
    for pattern in _INJECTION_PATTERNS:
        m = pattern.search(text)
        if m:
            matches.append(m.group(0))
    return matches


def contains_prompt_injection(text: str) -> bool:
    return bool(detect_prompt_injection(text))
