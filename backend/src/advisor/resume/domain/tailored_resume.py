"""A résumé written for one Target, and its saved versions."""

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


@dataclass(slots=True)
class TailoredResume:
    id: uuid.UUID
    owner_id: uuid.UUID
    # The Target (ADR 0022): one of the user's roles and optionally one
    # opening in it, or a posting of the user's own (Phase 8). Plain ids: the
    # target component owns what they mean.
    role_id: uuid.UUID | None
    job_posting_id: uuid.UUID | None
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
    private_job_posting_id: uuid.UUID | None = None
    # What the latest generated version read (ADR 0035): the profile version
    # and the Target's digest. A manual edit or an applied revision reads
    # neither and leaves them alone. None before the first write, and on
    # résumés written before they were recorded.
    profile_version: int | None = None
    target_digest: str | None = None

    @classmethod
    def requested(
        cls,
        *,
        owner_id: uuid.UUID,
        role_id: uuid.UUID | None,
        job_posting_id: uuid.UUID | None,
        label: str,
        template: Template,
        options: Options,
        at: datetime,
        private_job_posting_id: uuid.UUID | None = None,
    ) -> TailoredResume:
        return cls(
            id=uuid.uuid4(),
            owner_id=owner_id,
            role_id=role_id,
            job_posting_id=job_posting_id,
            private_job_posting_id=private_job_posting_id,
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
        profile_version: int,
        target_digest: str,
        at: datetime,
    ) -> None:
        self.snapshot = snapshot
        self.profile_version = profile_version
        self.target_digest = target_digest
        self.target_label = label[:400]
        self.coverage = coverage
        self.status = ResumeStatus.READY
        self.updated_at = at

    def redraft(self, at: datetime) -> None:
        """Write it again for the same Target, as its next version."""
        self.status = ResumeStatus.DRAFTING
        self.error_code = None
        self.error_message = None
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
