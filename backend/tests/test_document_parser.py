"""Document validation + text-first extraction (design §22.1, §22.2, §29).
PDFs and DOCX fixtures are built in-memory with the same libraries the
parser uses (PyMuPDF / python-docx) rather than checked-in binary files.
"""
from __future__ import annotations

import io

import pymupdf
import pytest
from docx import Document as DocxDocument

from app.profiling.document_parser import (
    CorruptDocumentError,
    DocumentTooLargeError,
    MAX_UPLOAD_BYTES,
    UnsupportedDocumentError,
    classify_extension,
    extract_text,
    sniff_content_matches_type,
    validate_upload,
)


def _build_pdf_bytes(text: str) -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


def _build_docx_bytes(paragraphs: list[str]) -> bytes:
    doc = DocxDocument()
    for p in paragraphs:
        doc.add_paragraph(p)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# -- PDF -----------------------------------------------------------------


def test_pdf_extraction_returns_text():
    pdf_bytes = _build_pdf_bytes("Skilled in Python and SQL.")
    result = extract_text("pdf", pdf_bytes)
    assert "Python" in result.text
    assert result.page_count == 1
    assert result.needs_vlm_fallback is False


def test_pdf_extraction_empty_page_needs_vlm_fallback():
    doc = pymupdf.open()
    doc.new_page()  # a blank page, no text -- simulates a scanned image PDF
    data = doc.tobytes()
    doc.close()

    result = extract_text("pdf", data)
    assert result.text == ""
    assert result.needs_vlm_fallback is True


def test_pdf_extraction_rejects_corrupt_bytes():
    with pytest.raises(CorruptDocumentError):
        extract_text("pdf", b"not a real pdf")


def test_pdf_page_limit_enforced():
    doc = pymupdf.open()
    for _ in range(3):
        doc.new_page()
    data = doc.tobytes()
    doc.close()

    import app.profiling.document_parser as dp

    original_limit = dp.MAX_PDF_PAGES
    dp.MAX_PDF_PAGES = 2
    try:
        with pytest.raises(DocumentTooLargeError):
            extract_text("pdf", data)
    finally:
        dp.MAX_PDF_PAGES = original_limit


# -- DOCX -----------------------------------------------------------------


def test_docx_extraction_returns_paragraph_text():
    docx_bytes = _build_docx_bytes(["Experience", "Built a data pipeline using Python and Airflow."])
    result = extract_text("docx", docx_bytes)
    assert "Built a data pipeline using Python and Airflow." in result.text
    assert result.needs_vlm_fallback is False


def test_docx_extraction_empty_document_needs_vlm_fallback():
    docx_bytes = _build_docx_bytes([])
    result = extract_text("docx", docx_bytes)
    assert result.text == ""
    assert result.needs_vlm_fallback is True


def test_docx_extraction_rejects_corrupt_bytes():
    with pytest.raises(CorruptDocumentError):
        extract_text("docx", b"PK\x03\x04not a real docx")


# -- Plain text -------------------------------------------------------------


def test_plain_text_extraction():
    result = extract_text("text", "Familiar with SQL and Docker.".encode("utf-8"))
    assert result.text == "Familiar with SQL and Docker."
    assert result.needs_vlm_fallback is False


def test_plain_text_latin1_fallback_decoding():
    result = extract_text("text", "café".encode("latin-1"))
    assert "caf" in result.text


# -- Image (always needs VLM) -------------------------------------------------


def test_image_always_needs_vlm_fallback():
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
    result = extract_text("image", png_bytes)
    assert result.text == ""
    assert result.needs_vlm_fallback is True


# -- validate_upload (type/size/MIME) ----------------------------------------


def test_classify_extension_rejects_unknown_extension():
    with pytest.raises(UnsupportedDocumentError):
        classify_extension("resume.exe")


def test_classify_extension_supported_types():
    assert classify_extension("resume.pdf") == "pdf"
    assert classify_extension("resume.docx") == "docx"
    assert classify_extension("resume.txt") == "text"
    assert classify_extension("resume.md") == "text"
    assert classify_extension("certificate.png") == "image"


def test_sniff_content_rejects_mismatched_magic_bytes():
    assert sniff_content_matches_type(b"not a pdf at all", "pdf") is False
    assert sniff_content_matches_type(b"%PDF-1.7 ...", "pdf") is True


def test_validate_upload_rejects_renamed_file_with_wrong_magic():
    fake_pdf = b"MZ\x90\x00" + b"\x00" * 20  # an EXE header renamed to .pdf
    with pytest.raises(UnsupportedDocumentError):
        validate_upload("resume.pdf", fake_pdf)


def test_validate_upload_rejects_oversized_file():
    huge = b"a" * (MAX_UPLOAD_BYTES + 1)
    with pytest.raises(DocumentTooLargeError):
        validate_upload("notes.txt", huge)


def test_validate_upload_rejects_empty_file():
    with pytest.raises(CorruptDocumentError):
        validate_upload("notes.txt", b"")


def test_validate_upload_accepts_well_formed_pdf():
    pdf_bytes = _build_pdf_bytes("hello")
    doc_type = validate_upload("resume.pdf", pdf_bytes)
    assert doc_type == "pdf"
