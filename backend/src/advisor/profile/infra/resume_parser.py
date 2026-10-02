"""Turning an uploaded resume into Evidence.

Runs in the worker only, never in a request handler, under size, page-count
and time limits. The file is untrusted: a PDF is an execution format, and a
resume is a document a stranger uploaded (docs/architecture.md
section 4). Its text is read by ``kernel.documents``.

No LLM is involved here. The text is split into traceable lines so every claim
the assessment later makes can point at a specific part of the document.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from advisor.profile.infra.connectors.base import EvidenceDraft
from kernel.documents import ACCEPTED_TYPES, read_document_text
from kernel.errors import ValidationError

# A resume line shorter than this is a heading or a stray token, not a claim.
_MIN_LINE_LENGTH = 24
_MAX_LINES = 120
_BULLET = re.compile(r"^[\s\-•●▪*+]+")


@dataclass(frozen=True, slots=True)
class ParsedResume:
    text: str
    page_count: int
    drafts: list[EvidenceDraft]


def parse(content: bytes, *, content_type: str, filename: str, max_pages: int) -> ParsedResume:
    if content_type not in ACCEPTED_TYPES:
        raise ValidationError(
            f"{content_type} is not a resume format we can read", content_type=content_type
        )

    text, pages = read_document_text(content, content_type=content_type, max_pages=max_pages)

    if not text.strip():
        raise ValidationError("no text could be read from this file", filename=filename)

    return ParsedResume(text=text, page_count=pages, drafts=_to_drafts(text, filename))


def _to_drafts(text: str, filename: str) -> list[EvidenceDraft]:
    """One draft per substantive line, each pointing back at where it came from."""
    drafts: list[EvidenceDraft] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        line = _BULLET.sub("", raw).strip()
        if len(line) < _MIN_LINE_LENGTH:
            continue
        drafts.append(
            EvidenceDraft(
                external_ref=f"resume:{filename}:{number}",
                reference=f"Resume · {filename} · line {number}",
                fact=line,
                observed_on=None,
            )
        )
        if len(drafts) >= _MAX_LINES:
            break
    return drafts
