"""A posting of the user's own: a JD they pasted to aim the Advisor at
(Phase 8). It is never on the role map, and no build reads or scores it.

Its text lives in ``market_user.private_job_posting``, which the crawler cannot
reach. What the role map keeps is what the user's key read out of it: its
requirements, read once, and the run that read and scored them, which the
Advisor polls.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from advisor.rolemap.domain.constants import MAX_COMPANY_NAME, MAX_ROLE_TITLE


class OwnPostingError(ValueError):
    """A posting of the user's own that cannot be added as asked."""


def parse_own_posting(
    *, title: str, company_name: str | None, job_description: str
) -> tuple[str, str | None, str]:
    """The title, company and JD as stored, or why they cannot be: a JD is
    required, since nothing else says what the posting asks for."""
    name = title.strip()
    if not name:
        raise OwnPostingError("a posting of your own needs a job title")
    if len(name) > MAX_ROLE_TITLE:
        raise OwnPostingError(f"a job title is at most {MAX_ROLE_TITLE} characters")
    company = (company_name or "").strip() or None
    if company is not None and len(company) > MAX_COMPANY_NAME:
        raise OwnPostingError(f"a company name is at most {MAX_COMPANY_NAME} characters")
    description = job_description.strip()
    if not description:
        raise OwnPostingError("a posting of your own needs its job description")
    return name, company, description


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


@dataclass(slots=True)
class PostingRequirement:
    """Free text read out of a posting of the user's own: what its JD asks
    for. It has no dimension; the fit maps it onto the user's."""

    id: uuid.UUID
    owner_id: uuid.UUID
    private_job_posting_id: uuid.UUID
    statement: str
    weight: float
    expected_level: str
