"""The Resume Advisor's entities: a résumé tailored to one Target, its versions,
the revision chat, and PDF exports.

A résumé holds its Target as a kind and one id, plus the frozen snapshot it was
written against. Versions are never overwritten; every save adds one.
``advisor.resume.infra`` maps these to and from the database.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from advisor.resume.domain.content import Options, Template, VersionSource


class ResumeStatus(StrEnum):
    DRAFTING = "drafting"
    READY = "ready"
    FAILED = "failed"


class ExportStatus(StrEnum):
    RENDERING = "rendering"
    READY = "ready"
    FAILED = "failed"


@dataclass(slots=True)
class TailoredResume:
    id: uuid.UUID
    owner_id: uuid.UUID
    # A TargetKind value from the target component, and the id it points at.
    target_kind: str
    target_id: uuid.UUID
    target_label: str
    template: Template
    options: Options
    status: ResumeStatus
    created_at: datetime
    updated_at: datetime
    snapshot: dict[str, Any] | None = None
    coverage: tuple[dict[str, Any], ...] = ()
    error_code: str | None = None
    error_message: str | None = None

    @classmethod
    def requested(
        cls,
        *,
        owner_id: uuid.UUID,
        target_kind: str,
        target_id: uuid.UUID,
        label: str,
        template: Template,
        options: Options,
        at: datetime,
    ) -> TailoredResume:
        return cls(
            id=uuid.uuid4(),
            owner_id=owner_id,
            target_kind=target_kind,
            target_id=target_id,
            target_label=label[:400],
            template=template,
            options=options,
            status=ResumeStatus.DRAFTING,
            created_at=at,
            updated_at=at,
        )

    def written(
        self,
        *,
        snapshot: dict[str, Any],
        label: str,
        coverage: tuple[dict[str, Any], ...],
        at: datetime,
    ) -> None:
        self.snapshot = snapshot
        self.target_label = label[:400]
        self.coverage = coverage
        self.status = ResumeStatus.READY
        self.updated_at = at

    def restyle(self, *, template: Template, options: Options, at: datetime) -> None:
        self.template = template
        self.options = options
        self.updated_at = at

    def touched(self, at: datetime) -> None:
        """A new version counts as a change to the résumé."""
        self.updated_at = at

    def failed(self, *, code: str, message: str, at: datetime) -> None:
        self.status = ResumeStatus.FAILED
        self.error_code = code
        self.error_message = message
        self.updated_at = at


@dataclass(slots=True)
class ResumeVersion:
    id: uuid.UUID
    owner_id: uuid.UUID
    resume_id: uuid.UUID
    number: int
    label: str
    content: dict[str, Any]
    source: VersionSource
    created_at: datetime
    model_id: str | None = None
    template_version: str | None = None


@dataclass(slots=True)
class Revision:
    """One exchange in the revision chat: the request, the reply, the edit."""

    id: uuid.UUID
    owner_id: uuid.UUID
    resume_id: uuid.UUID
    request: str
    reply: str
    proposal: dict[str, Any] | None
    model_id: str
    template_version: str
    created_at: datetime
    applied_version_id: uuid.UUID | None = None


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
