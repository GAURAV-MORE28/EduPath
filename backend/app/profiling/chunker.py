"""Chunking with offsets (design §22.1 pipeline stage 3: "chunk with
offsets"). Splits on blank-line paragraph boundaries so each chunk is a
coherent section (a "Skills" list, one project bullet, one job entry) —
better for both extraction quality and span-verification locality than a
fixed-width sliding window. Falls back to fixed-width splitting only when a
single paragraph itself exceeds `max_chars` (a wall of text with no blank
lines).

Offsets are always relative to the *scrubbed* document text (see
`app/profiling/pii.py`) — this is what the Profiler sees and what
`ExtractedClaim.span_offsets` and the Evidence Verifier both index into.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n")

DEFAULT_MAX_CHARS = 2000


@dataclass
class TextChunk:
    text: str
    start_offset: int
    end_offset: int  # exclusive


def chunk_text(text: str, max_chars: int = DEFAULT_MAX_CHARS) -> list[TextChunk]:
    if not text:
        return []

    chunks: list[TextChunk] = []
    cursor = 0
    for match in _PARAGRAPH_SPLIT_RE.finditer(text):
        _emit_paragraph(text[cursor : match.start()], cursor, max_chars, chunks)
        cursor = match.end()
    _emit_paragraph(text[cursor:], cursor, max_chars, chunks)

    return [c for c in chunks if c.text.strip()]


def _emit_paragraph(paragraph: str, base_offset: int, max_chars: int, out: list[TextChunk]) -> None:
    if not paragraph.strip():
        return
    if len(paragraph) <= max_chars:
        out.append(TextChunk(text=paragraph, start_offset=base_offset, end_offset=base_offset + len(paragraph)))
        return
    # Oversized paragraph: fixed-width fallback split.
    for i in range(0, len(paragraph), max_chars):
        piece = paragraph[i : i + max_chars]
        out.append(
            TextChunk(text=piece, start_offset=base_offset + i, end_offset=base_offset + i + len(piece))
        )
