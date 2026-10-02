"""Reading the text out of a document a user uploaded: a PDF, a Word file or
plain text.

The file is untrusted. A PDF is an execution format, and the document is one a
stranger uploaded, so this runs in the worker only, never in a request handler,
under a page limit (docs/architecture.md section 4). Shared by the résumé
parser and postings of the user's own; what the text means is theirs.
"""

from __future__ import annotations

import io

from kernel.errors import ValidationError

PDF_TYPE = "application/pdf"
DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
TEXT_TYPE = "text/plain"
ACCEPTED_TYPES = frozenset({PDF_TYPE, DOCX_TYPE, TEXT_TYPE})


def read_document_text(content: bytes, *, content_type: str, max_pages: int) -> tuple[str, int]:
    """The document's text and its page count. A Word or text file counts as
    one page. Raises ``ValidationError`` for a type it cannot read, a file it
    cannot open, or one longer than ``max_pages``."""
    if content_type == PDF_TYPE:
        return _read_pdf(content, max_pages=max_pages)
    if content_type == DOCX_TYPE:
        return _read_docx(content)
    if content_type == TEXT_TYPE:
        return content.decode("utf-8", errors="replace"), 1
    raise ValidationError(f"{content_type} is not a format we can read", content_type=content_type)


def _read_pdf(content: bytes, *, max_pages: int) -> tuple[str, int]:
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(content))
    except Exception as exc:
        raise ValidationError("this PDF could not be opened") from exc

    if len(reader.pages) > max_pages:
        raise ValidationError(
            f"a document of more than {max_pages} pages is not accepted",
            pages=len(reader.pages),
        )
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n".join(pages), len(pages)


def _read_docx(content: bytes) -> tuple[str, int]:
    from docx import Document

    try:
        document = Document(io.BytesIO(content))
    except Exception as exc:
        raise ValidationError("this Word document could not be opened") from exc
    paragraphs = [p.text for p in document.paragraphs if p.text.strip()]
    return "\n".join(paragraphs), 1
