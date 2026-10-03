"""A posting of the user's own: a job they found that the role map does not
show, brought to the Advisor to aim at (ADR 0030, ADR 0033).

It is a Target, never a role: no build reads it, and nothing outside its owner
sees it. It lives in the ``target`` schema, which the crawler has no grant on.
Its JD is uploaded as a file the worker reads, or the user fills the role in
by hand: a title, and optionally what it asks for (ADR 0034). Adding one spends
nothing; it is read and scored when it is set as the Advisor's target.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from advisor.target.domain.constants import (
    MAX_COMPANY_NAME,
    MAX_FILENAME,
    MAX_JOB_DESCRIPTION,
    MAX_REQUIREMENT_LINE,
    MAX_REQUIREMENT_LINES,
    MAX_TITLE,
)


class OwnPostingError(ValueError):
    """A posting of the user's own that cannot be added as asked."""


def parse_title_and_company(*, title: str, company_name: str | None) -> tuple[str, str | None]:
    """The title and company as stored, or why they cannot be."""
    name = title.strip()
    if not name:
        raise OwnPostingError("a posting of your own needs a job title")
    if len(name) > MAX_TITLE:
        raise OwnPostingError(f"a job title is at most {MAX_TITLE} characters")
    company = (company_name or "").strip() or None
    if company is not None and len(company) > MAX_COMPANY_NAME:
        raise OwnPostingError(f"a company name is at most {MAX_COMPANY_NAME} characters")
    return name, company


def parse_requirement_lines(lines: Sequence[str]) -> tuple[str, ...]:
    """What a role filled in by hand asks for, one requirement per line, or why
    it cannot be stored. Blank lines are dropped; none at all is allowed, and
    then its requirements are estimated from its title."""
    kept = tuple(line.strip() for line in lines if line.strip())
    if len(kept) > MAX_REQUIREMENT_LINES:
        raise OwnPostingError(f"list at most {MAX_REQUIREMENT_LINES} requirements")
    if any(len(line) > MAX_REQUIREMENT_LINE for line in kept):
        raise OwnPostingError(f"a requirement is at most {MAX_REQUIREMENT_LINE} characters")
    return kept


def get_placeholder_title(filename: str) -> str:
    """What an uploaded JD is called until it is read: its file's name without
    the extension. Pure."""
    stem = filename.strip().rsplit(".", 1)[0].strip() if "." in filename else filename.strip()
    return (stem or "Job description")[:MAX_TITLE]


class PostingSource(StrEnum):
    """How the role arrived: uploaded as a file whose text the worker reads
    before anything else (ADR 0033), or filled in by hand (ADR 0034). Pasted
    JDs are no longer taken, but those already stored keep their source."""

    PASTED = "pasted"
    UPLOADED = "uploaded"
    FILLED_IN = "filled_in"


@dataclass(slots=True)
class PrivateJobPosting:
    """A posting of the user's own: the JD they brought. Private to them,
    always.

    An uploaded one has no JD until the worker has read its file
    (``storage_key``); the file is deleted once it has been read. One uploaded
    without a title is named after its file until then
    (``has_placeholder_title``), and after the job the file names.

    One filled in by hand keeps what it asks for as its JD, one requirement per
    line, or none at all: then ``has_estimated_requirements``, and what it asks
    for is estimated from its title when it is read.
    """

    id: uuid.UUID
    owner_id: uuid.UUID
    title: str
    company_name: str | None
    job_description: str | None
    source: PostingSource = PostingSource.PASTED
    filename: str | None = None
    content_type: str | None = None
    storage_key: str | None = None
    has_placeholder_title: bool = False
    has_estimated_requirements: bool = False
    created_at: datetime | None = None

    @classmethod
    def filled_in(
        cls,
        *,
        owner_id: uuid.UUID,
        title: str,
        company_name: str | None,
        requirements: Sequence[str],
    ) -> PrivateJobPosting:
        """A role filled in by hand: a title, and what it asks for if known."""
        name, company = parse_title_and_company(title=title, company_name=company_name)
        lines = parse_requirement_lines(requirements)
        return cls(
            id=uuid.uuid4(),
            owner_id=owner_id,
            title=name,
            company_name=company,
            job_description="\n".join(f"- {line}" for line in lines) or None,
            source=PostingSource.FILLED_IN,
            has_estimated_requirements=not lines,
        )

    @classmethod
    def uploaded(
        cls,
        *,
        owner_id: uuid.UUID,
        title: str | None,
        company_name: str | None,
        filename: str,
        content_type: str,
        storage_key: str,
    ) -> PrivateJobPosting:
        """A JD uploaded as a file, stored under ``storage_key`` until it is
        read. Without a title, it is named after its file until then."""
        shown_filename = (filename.strip() or "job description")[:MAX_FILENAME]
        is_untitled = not (title or "").strip()
        name, company = parse_title_and_company(
            title=get_placeholder_title(shown_filename) if is_untitled else title or "",
            company_name=company_name,
        )
        return cls(
            id=uuid.uuid4(),
            owner_id=owner_id,
            title=name,
            company_name=company,
            job_description=None,
            source=PostingSource.UPLOADED,
            filename=shown_filename,
            content_type=content_type,
            storage_key=storage_key,
            has_placeholder_title=is_untitled,
        )

    @property
    def is_read(self) -> bool:
        """Whether its JD is there to read requirements from."""
        return self.job_description is not None

    @property
    def is_waiting_for_its_file(self) -> bool:
        """An uploaded JD whose file the worker has not read yet."""
        return self.storage_key is not None

    def update_title(self, name: str) -> None:
        """Name it after the job its JD turned out to be, if the user gave it no
        title of their own. Keeps the placeholder when the name is blank."""
        if not self.has_placeholder_title:
            return
        clipped = name.strip()[:MAX_TITLE]
        if clipped:
            self.title = clipped
            self.has_placeholder_title = False

    def read(self, text: str) -> None:
        """The text read out of its file becomes its JD, cut to the longest a
        JD may be, and the file is no longer needed."""
        clipped = text.strip()[:MAX_JOB_DESCRIPTION]
        if not clipped:
            raise OwnPostingError("no text could be read from this file")
        self.job_description = clipped
        self.storage_key = None


class PostingEvaluationStatus(StrEnum):
    """Reading and scoring run in the background, so the run is recorded
    before it is queued and the Advisor polls it (ADR 0006)."""

    RUNNING = "running"
    READY = "ready"
    FAILED = "failed"
    # Stopped by the user (ADR 0042): never shown; the run before it stands.
    CANCELLED = "cancelled"


class EvaluationStage(StrEnum):
    """Where evaluating a posting has got, recorded as it passes (ADR 0042).
    Its calls go through the role map's kit, so there is no streamed share
    within a stage."""

    READING_FILE = "reading_file"
    READING_REQUIREMENTS = "reading_requirements"
    SCORING = "scoring"
    WORKING_OUT_FIT = "working_out_fit"


@dataclass(slots=True)
class PostingEvaluation:
    """One run of reading a posting of the user's own and scoring it, on the
    user's key. ``reads_requirements`` is false for a rescore, which keeps the
    requirements read when the posting was added."""

    id: uuid.UUID
    owner_id: uuid.UUID
    private_job_posting_id: uuid.UUID
    status: PostingEvaluationStatus
    reads_requirements: bool
    requested_at: datetime
    finished_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None
    stage: EvaluationStage | None = None
    # 0 to 1, never going backwards.
    progress: float = 0.0

    @classmethod
    def requested(
        cls,
        *,
        owner_id: uuid.UUID,
        private_job_posting_id: uuid.UUID,
        reads_requirements: bool,
        at: datetime,
    ) -> PostingEvaluation:
        return cls(
            id=uuid.uuid4(),
            owner_id=owner_id,
            private_job_posting_id=private_job_posting_id,
            status=PostingEvaluationStatus.RUNNING,
            reads_requirements=reads_requirements,
            requested_at=at,
        )

    @property
    def is_running(self) -> bool:
        return self.status is PostingEvaluationStatus.RUNNING

    def ready(self, at: datetime) -> None:
        self.status = PostingEvaluationStatus.READY
        self.finished_at = at

    def failed(self, *, code: str, message: str, at: datetime) -> None:
        self.status = PostingEvaluationStatus.FAILED
        self.error_code = code
        self.error_message = message
        self.finished_at = at

    def update_stage(self, stage: EvaluationStage, *, progress: float) -> None:
        self.stage = stage
        self.progress = max(self.progress, progress)

    def update_cancelled(self, at: datetime) -> None:
        if not self.is_running:
            raise OwnPostingError("only a posting still being scored can be cancelled")
        self.status = PostingEvaluationStatus.CANCELLED
        self.finished_at = at
