"""A download's Content-Disposition (ADR 0038): an ASCII name every browser
reads, and the exact name in UTF-8."""

from __future__ import annotations

from kernel.storage import attachment_disposition


def test_an_ascii_name_is_given_as_is_and_encoded() -> None:
    assert attachment_disposition("Maya Chen.pdf") == (
        "attachment; filename=\"Maya Chen.pdf\"; filename*=UTF-8''Maya%20Chen.pdf"
    )


def test_a_name_outside_ascii_keeps_its_letters_in_the_utf8_form() -> None:
    header = attachment_disposition("Résumé — Staff.pdf")

    assert 'filename="Rsum  Staff.pdf"' in header
    assert "filename*=UTF-8''R%C3%A9sum%C3%A9%20%E2%80%94%20Staff.pdf" in header


def test_quotes_cannot_end_the_plain_name_early() -> None:
    assert 'filename="a b.pdf"' in attachment_disposition('a "b.pdf')
