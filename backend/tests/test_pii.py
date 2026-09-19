"""PII scrubbing (design §22.1, §29 "Data privacy")."""
from __future__ import annotations

from app.profiling.pii import scrub_pii


def test_scrubs_email():
    text = "Reach me at jane.doe@example.com for details."
    scrubbed, redactions = scrub_pii(text)
    assert "jane.doe@example.com" not in scrubbed
    assert "[REDACTED_EMAIL]" in scrubbed
    assert any(r.kind == "email" for r in redactions)


def test_scrubs_phone_number():
    text = "Call 555-123-4567 anytime."
    scrubbed, redactions = scrub_pii(text)
    assert "555-123-4567" not in scrubbed
    assert "[REDACTED_PHONE]" in scrubbed
    assert any(r.kind == "phone" for r in redactions)


def test_scrubs_street_address():
    text = "I live at 123 Main Street in the city."
    scrubbed, redactions = scrub_pii(text)
    assert "123 Main Street" not in scrubbed
    assert "[REDACTED_ADDRESS]" in scrubbed


def test_leaves_skill_text_untouched():
    text = "Proficient in Python, SQL, and Docker since 2020."
    scrubbed, redactions = scrub_pii(text)
    assert "Python" in scrubbed
    assert "SQL" in scrubbed
    assert "Docker" in scrubbed


def test_no_false_positive_on_plain_sentence():
    text = "Trained a model for 3 epochs with a batch size of 32."
    scrubbed, redactions = scrub_pii(text)
    assert scrubbed == text
    assert redactions == []
