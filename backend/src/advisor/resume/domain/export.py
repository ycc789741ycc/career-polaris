"""A PDF export of one résumé version, rendered on the ``docs`` queue
(ADR 0007).
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

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
    # The built-in template it was rendered in; None for one of the user's own.
    template: Template | None
    status: ExportStatus
    created_at: datetime
    # Whether it was cut to one page, read when Export was clicked: with the
    # version and the template, what an export rendered, so an unchanged one
    # is reused (ADR 0038). None on exports from before it was kept.
    trim: bool | None = None
    # The look it was rendered in, as ``TemplateSpec.to_dict()``: what a
    # reuse compares, so a template edited since is rendered again (ADR 0040).
    # None on exports from before it was kept.
    spec: dict[str, Any] | None = None
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


def get_download_name(name: str, label: str) -> str:
    """The file a downloaded résumé is saved as: "<name> — <role>.pdf".

    The person's name and the Target's label, with anything a file name
    cannot hold taken out. A browser saves it under this name; it never
    reaches a path on the platform.
    """
    stem = " — ".join(part for part in (name.strip(), label.strip()) if part) or "Résumé"
    stem = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', " ", stem)
    stem = re.sub(r"\s+", " ", stem).strip()[:120]
    return f"{stem}.pdf"
