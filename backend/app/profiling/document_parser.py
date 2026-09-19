"""Document upload validation + text-first extraction (design §22.1, §22.2,
§29 "Malicious uploads"). PDF via PyMuPDF, DOCX via python-docx, TXT/MD read
directly. Images (PNG/JPG, for scanned certificates per §22.2) have no
extractable text — they always need the VLM fallback (`app/gateway/vlm_gateway.py`).

Pipeline stage 1 of 4 (design §22.1): `Upload -> validate -> store -> extract
text (-> VLM fallback if empty/image)`. PII scrubbing and chunking are the
next stages (`app/profiling/pii.py`, `app/profiling/chunker.py`).
"""
from __future__ import annotations

from dataclasses import dataclass

import pymupdf
from docx import Document as DocxDocument

# design §29 "Malicious uploads": whitelist (PDF, DOCX, TXT/MD, PNG/JPG).
SUPPORTED_DOCUMENT_TYPES = frozenset({"pdf", "docx", "text", "image"})

_EXTENSION_TO_TYPE = {
    "pdf": "pdf",
    "docx": "docx",
    "txt": "text",
    "md": "text",
    "markdown": "text",
    "png": "image",
    "jpg": "image",
    "jpeg": "image",
}

_MAGIC_BYTES = {
    "pdf": (b"%PDF-",),
    "docx": (b"PK\x03\x04",),  # DOCX is a zip archive
    "png": (b"\x89PNG\r\n\x1a\n",),
    "jpg": (b"\xff\xd8\xff",),
}

# design §29: size/page caps.
MAX_UPLOAD_BYTES = 15 * 1024 * 1024  # 15 MB
MAX_PDF_PAGES = 50


class UnsupportedDocumentError(ValueError):
    pass


class DocumentTooLargeError(ValueError):
    pass


class CorruptDocumentError(ValueError):
    pass


@dataclass
class ExtractionResult:
    text: str
    doc_type: str
    page_count: int | None
    needs_vlm_fallback: bool  # empty/unreadable text (scanned PDF) or a raw image


def classify_extension(filename: str) -> str:
    """Maps a filename extension to one of `SUPPORTED_DOCUMENT_TYPES`.
    Raises `UnsupportedDocumentError` for anything not on the whitelist —
    the caller must not guess or silently accept an unknown type.
    """
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    doc_type = _EXTENSION_TO_TYPE.get(ext)
    if doc_type is None:
        raise UnsupportedDocumentError(f"Unsupported file extension: {ext!r}")
    return doc_type


def sniff_content_matches_type(content: bytes, doc_type: str) -> bool:
    """MIME sniffing (design §29): the file's magic bytes must match its
    claimed type — a renamed executable claiming to be a `.pdf` is rejected.
    Plain text has no reliable magic; it is accepted if the extension said
    so and decoding succeeds (checked by the text extractor itself)."""
    if doc_type == "text":
        return True
    magics = _MAGIC_BYTES.get(doc_type) or (_MAGIC_BYTES.get("jpg") if doc_type == "image" else None)
    if doc_type == "image":
        return content.startswith(_MAGIC_BYTES["png"]) or content.startswith(_MAGIC_BYTES["jpg"])
    if magics is None:
        return True
    return any(content.startswith(sig) for sig in magics)


def validate_upload(filename: str, content: bytes) -> str:
    """Validates type/size/MIME per design §29. Returns the classified
    `doc_type`. Raises on any failure — never silently coerces."""
    if len(content) == 0:
        raise CorruptDocumentError("Uploaded file is empty")
    if len(content) > MAX_UPLOAD_BYTES:
        raise DocumentTooLargeError(f"Upload exceeds the {MAX_UPLOAD_BYTES} byte limit")
    doc_type = classify_extension(filename)
    if not sniff_content_matches_type(content, doc_type):
        raise UnsupportedDocumentError(f"File content does not match its claimed type ({doc_type})")
    return doc_type


def extract_text(doc_type: str, content: bytes) -> ExtractionResult:
    """Text-first extraction (design §22.1). Never raises for an
    empty/scanned/image document — those degrade to `needs_vlm_fallback=True`
    (design §30: "Unreadable/empty PDF -> VLM fallback -> still empty -> ask
    user to paste text"), matching graceful-degradation (P7)."""
    if doc_type == "pdf":
        return _extract_pdf(content)
    if doc_type == "docx":
        return _extract_docx(content)
    if doc_type == "text":
        return _extract_plain_text(content)
    if doc_type == "image":
        return ExtractionResult(text="", doc_type=doc_type, page_count=None, needs_vlm_fallback=True)
    raise UnsupportedDocumentError(f"Unsupported doc_type: {doc_type!r}")


def _extract_pdf(content: bytes) -> ExtractionResult:
    try:
        pdf = pymupdf.open(stream=content, filetype="pdf")
    except Exception as exc:  # noqa: BLE001 - any PyMuPDF parse failure is a corrupt/unsupported file
        raise CorruptDocumentError(f"Could not parse PDF: {exc}") from exc

    try:
        if pdf.page_count > MAX_PDF_PAGES:
            raise DocumentTooLargeError(f"PDF has {pdf.page_count} pages, limit is {MAX_PDF_PAGES}")
        pages_text = [page.get_text() for page in pdf]
    finally:
        pdf.close()

    text = "\n".join(pages_text).strip()
    return ExtractionResult(text=text, doc_type="pdf", page_count=len(pages_text), needs_vlm_fallback=not text)


def _extract_docx(content: bytes) -> ExtractionResult:
    import io

    try:
        doc = DocxDocument(io.BytesIO(content))
    except Exception as exc:  # noqa: BLE001
        raise CorruptDocumentError(f"Could not parse DOCX: {exc}") from exc

    parts = [p.text for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                if cell.text.strip():
                    parts.append(cell.text)

    text = "\n".join(parts).strip()
    return ExtractionResult(text=text, doc_type="docx", page_count=None, needs_vlm_fallback=not text)


def _extract_plain_text(content: bytes) -> ExtractionResult:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = content.decode("latin-1")
        except UnicodeDecodeError as exc:
            raise CorruptDocumentError("Could not decode text file as UTF-8 or Latin-1") from exc

    text = text.strip()
    return ExtractionResult(text=text, doc_type="text", page_count=None, needs_vlm_fallback=not text)
