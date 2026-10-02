"""A PDF export of one résumé version, rendered on the ``docs`` queue
(ADR 0007).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from advisor.resume.domain.content import Template


class ExportStatus(StrEnum):
    RENDERING = "rendering"
    READY = "ready"
    FAILED = "failed"


@dataclass(slots=True)
class Export:
    id: uuid.UUID
    owner_id: uuid.UUID
    version_id: uuid.UUID
    template: Template
    status: ExportStatus
    created_at: datetime
    storage_key: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    finished_at: datetime | None = None

    def rendered(self, storage_key: str, *, at: datetime) -> None:
        self.status = ExportStatus.READY
        self.storage_key = storage_key
        self.finished_at = at

    def failed(self, *, code: str, message: str, at: datetime) -> None:
        self.status = ExportStatus.FAILED
        self.error_code = code
        self.error_message = message
        self.finished_at = at
