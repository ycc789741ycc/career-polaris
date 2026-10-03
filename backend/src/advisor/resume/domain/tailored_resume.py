"""A résumé written for one Target, and its saved versions."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from advisor.resume.domain.content import Options, Template, VersionSource
from advisor.resume.domain.section import DEFAULT_PLAN, SectionSlot


class ResumeStatus(StrEnum):
    DRAFTING = "drafting"
    READY = "ready"
    FAILED = "failed"
    # Written, and one section being filled from the sources (ADR 0039): the
    # page stays readable, and a failure leaves it ready, with the reason.
    FILLING = "filling"
    # A first draft stopped by the user before it was written (ADR 0042):
    # never listed. A redraft or a section stopped leaves the résumé ready.
    CANCELLED = "cancelled"


class ResumeStage(StrEnum):
    """Where writing a résumé, or one section of it, has got (ADR 0042)."""

    READING = "reading"
    WRITING = "writing"
    CHECKING = "checking"
    SAVING = "saving"


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
    # A built-in template, or None when one of the user's own is chosen
    # (``custom_template_id``): exactly one of the two (ADR 0040).
    template: Template | None
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
    # The sections every new version is written to, in order (ADR 0039).
    section_plan: tuple[SectionSlot, ...] = DEFAULT_PLAN
    custom_template_id: uuid.UUID | None = None
    stage: ResumeStage | None = None
    # 0 to 1, never going backwards within one job.
    progress: float = 0.0
    estimated_cost_usd: Decimal | None = None

    @classmethod
    def requested(
        cls,
        *,
        owner_id: uuid.UUID,
        role_id: uuid.UUID | None,
        job_posting_id: uuid.UUID | None,
        label: str,
        template: Template | None,
        options: Options,
        at: datetime,
        private_job_posting_id: uuid.UUID | None = None,
        custom_template_id: uuid.UUID | None = None,
    ) -> TailoredResume:
        if (template is None) == (custom_template_id is None):
            raise ValueError("a résumé has one template: built in, or of your own")
        return cls(
            id=uuid.uuid4(),
            owner_id=owner_id,
            role_id=role_id,
            job_posting_id=job_posting_id,
            private_job_posting_id=private_job_posting_id,
            target_label=label[:400],
            template=template,
            custom_template_id=custom_template_id,
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
        self._start_job()

    def update_plan(self, plan: tuple[SectionSlot, ...], *, at: datetime) -> None:
        """Sections added, removed or moved: what the next version is written to."""
        self.section_plan = plan
        self.updated_at = at

    def update_filling(self, *, at: datetime) -> None:
        """One section is being filled from the sources."""
        self.status = ResumeStatus.FILLING
        self.error_code = None
        self.error_message = None
        self.updated_at = at
        self._start_job()

    @property
    def is_busy(self) -> bool:
        """Being written, or a section of it being filled."""
        return self.status in (ResumeStatus.DRAFTING, ResumeStatus.FILLING)

    @property
    def is_shown(self) -> bool:
        return self.status is not ResumeStatus.CANCELLED

    def update_stage(
        self, stage: ResumeStage, *, progress: float, cost: Decimal | None = None
    ) -> None:
        self.stage = stage
        self.progress = max(self.progress, progress)
        if cost is not None:
            self.estimated_cost_usd = cost

    def update_cancelled(
        self, *, latest_plan: tuple[SectionSlot, ...] | None, at: datetime
    ) -> None:
        """Stop the job running on it. A résumé with a saved version goes back
        to it, its plan to that version's sections; a first draft is
        cancelled outright. ``latest_plan`` is the latest version's plan, or
        None when there is none."""
        if not self.is_busy:
            raise ValueError("only a résumé being written can be cancelled")
        if latest_plan is None:
            self.status = ResumeStatus.CANCELLED
        else:
            self.status = ResumeStatus.READY
            self.section_plan = latest_plan
        self.stage = None
        self.updated_at = at

    def _start_job(self) -> None:
        self.stage = None
        self.progress = 0.0
        self.estimated_cost_usd = None

    def update_filled(self, *, at: datetime) -> None:
        self.status = ResumeStatus.READY
        self.updated_at = at

    def update_fill_failed(self, *, code: str, message: str, at: datetime) -> None:
        """A section that could not be filled leaves the résumé as it was:
        ready, with the reason to show."""
        self.status = ResumeStatus.READY
        self.error_code = code
        self.error_message = message
        self.updated_at = at

    def restyle(
        self,
        *,
        template: Template | None,
        options: Options,
        at: datetime,
        custom_template_id: uuid.UUID | None = None,
    ) -> None:
        """A built-in template, or one of the user's own: exactly one."""
        if (template is None) == (custom_template_id is None):
            raise ValueError("a résumé has one template: built in, or of your own")
        self.template = template
        self.custom_template_id = custom_template_id
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
