"""An uploaded résumé, and how far parsing it has got."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class ResumeStatus(StrEnum):
    UPLOADED = "uploaded"
    PARSED = "parsed"
    FAILED = "failed"


@dataclass(slots=True)
class ResumeFile:
    """An uploaded résumé: a source of evidence, and the base document a
    tailored résumé revises rather than replaces."""

    id: uuid.UUID
    owner_id: uuid.UUID
    filename: str
    storage_key: str
    content_type: str
    byte_size: int
    status: ResumeStatus
    parse_error: str | None = None
    parsed_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def parsed(self, at: datetime) -> None:
        self.status = ResumeStatus.PARSED
        self.parsed_at = at
        self.parse_error = None

    def parse_failed(self, error: str) -> None:
        self.status = ResumeStatus.FAILED
        self.parse_error = error
