"""Reading text out of an uploaded document: the formats it reads, and the
ones it refuses before anything else sees them."""

from __future__ import annotations

import io

import pytest

from kernel.documents import DOCX_TYPE, PDF_TYPE, TEXT_TYPE, read_document_text
from kernel.errors import ValidationError


def _docx(*paragraphs: str) -> bytes:
    from docx import Document

    document = Document()
    for paragraph in paragraphs:
        document.add_paragraph(paragraph)
    out = io.BytesIO()
    document.save(out)
    return out.getvalue()


def _blank_pdf(pages: int) -> bytes:
    from pypdf import PdfWriter

    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=612, height=792)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def test_plain_text_is_read_as_one_page() -> None:
    assert read_document_text(
        b"Own the ledger.\nLead design.", content_type=TEXT_TYPE, max_pages=1
    ) == ("Own the ledger.\nLead design.", 1)


def test_a_word_file_is_read_paragraph_by_paragraph() -> None:
    text, pages = read_document_text(
        _docx("Staff Engineer", "", "Own the ledger."), content_type=DOCX_TYPE, max_pages=1
    )

    assert (text, pages) == ("Staff Engineer\nOwn the ledger.", 1)


def test_a_pdf_counts_its_pages() -> None:
    _text, pages = read_document_text(_blank_pdf(2), content_type=PDF_TYPE, max_pages=2)

    assert pages == 2


def test_a_pdf_longer_than_allowed_is_refused() -> None:
    with pytest.raises(ValidationError, match="more than 2 pages"):
        read_document_text(_blank_pdf(3), content_type=PDF_TYPE, max_pages=2)


@pytest.mark.parametrize(
    ("content", "content_type", "message"),
    [
        (b"not a pdf at all", PDF_TYPE, "could not be opened"),
        (b"not a word file", DOCX_TYPE, "could not be opened"),
        (b"\x89PNG", "image/png", "not a format we can read"),
    ],
)
def test_what_cannot_be_read_is_refused_with_a_readable_message(
    content: bytes, content_type: str, message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        read_document_text(content, content_type=content_type, max_pages=10)
