"""A posting of the user's own: a job they found that the role map does not
show, brought to the Advisor to aim at (ADR 0030, ADR 0033).

It is a Target, never a role: no build reads it, and nothing outside its owner
sees it. It lives in the ``target`` schema, which the crawler has no grant on.
Its JD is pasted, or uploaded as a file the worker reads.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from advisor.target.domain.constants import (
    MAX_COMPANY_NAME,
    MAX_FILENAME,
    MAX_JOB_DESCRIPTION,
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


def parse_job_description(job_description: str) -> str:
    """The JD as stored, or why it cannot be: a JD is required, since nothing
    else says what the posting asks for."""
    description = job_description.strip()
    if not description:
        raise OwnPostingError("a posting of your own needs its job description")
    if len(description) > MAX_JOB_DESCRIPTION:
        raise OwnPostingError(f"a job description is at most {MAX_JOB_DESCRIPTION} characters")
    return description


def parse_own_posting(
    *, title: str, company_name: str | None, job_description: str
) -> tuple[str, str | None, str]:
    """The title, company and JD as stored, or why they cannot be."""
    name, company = parse_title_and_company(title=title, company_name=company_name)
    return name, company, parse_job_description(job_description)


class PostingSource(StrEnum):
    """How the JD arrived: pasted as text, or uploaded as a file whose text the
    worker reads before anything else (ADR 0033)."""

    PASTED = "pasted"
    UPLOADED = "uploaded"


@dataclass(slots=True)
class PrivateJobPosting:
    """A posting of the user's own: the JD they brought. Private to them,
    always.

    An uploaded one has no JD until the worker has read its file
    (``storage_key``); the file is deleted once it has been read.
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
    created_at: datetime | None = None

    @classmethod
    def added(
        cls,
        *,
        owner_id: uuid.UUID,
        title: str,
        company_name: str | None,
        job_description: str,
    ) -> PrivateJobPosting:
        """A JD pasted as text."""
        name, company, description = parse_own_posting(
            title=title, company_name=company_name, job_description=job_description
        )
        return cls(
            id=uuid.uuid4(),
            owner_id=owner_id,
            title=name,
            company_name=company,
            job_description=description,
        )

    @classmethod
    def uploaded(
        cls,
        *,
        owner_id: uuid.UUID,
        title: str,
        company_name: str | None,
        filename: str,
        content_type: str,
        storage_key: str,
    ) -> PrivateJobPosting:
        """A JD uploaded as a file, stored under ``storage_key`` until it is
        read."""
        name, company = parse_title_and_company(title=title, company_name=company_name)
        return cls(
            id=uuid.uuid4(),
            owner_id=owner_id,
            title=name,
            company_name=company,
            job_description=None,
            source=PostingSource.UPLOADED,
            filename=(filename.strip() or "job description")[:MAX_FILENAME],
            content_type=content_type,
            storage_key=storage_key,
        )

    @property
    def is_read(self) -> bool:
        """Whether its JD is there to read requirements from."""
        return self.job_description is not None

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
