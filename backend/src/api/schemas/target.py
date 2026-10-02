"""Target's wire shapes: what a gap plan or a résumé is aimed at (ADR 0022),
and the postings of the user's own that one can aim at (ADR 0033).

A Target is a role on the user's role map and optionally one opening in it, or
a posting of the user's own (Phase 8): exactly one of ``role_id`` and
``private_job_posting_id``. Bodies and query strings carry the same three ids.
"""

from __future__ import annotations

import uuid
from typing import Literal, Self

from pydantic import Field, model_validator

from advisor.target import (
    MAX_COMPANY_NAME,
    MAX_JOB_DESCRIPTION,
    MAX_TITLE,
    OwnPostingView,
    TargetRef,
)
from api.schemas.common import ApiModel, Page, RequestModel, Timestamp


class TargetRefBody(ApiModel):
    """A role on the user's role map and optionally one opening in it, or a
    posting of the user's own."""

    role_id: uuid.UUID | None
    job_posting_id: uuid.UUID | None = None
    private_job_posting_id: uuid.UUID | None = None

    @classmethod
    def from_ref(cls, ref: TargetRef) -> TargetRefBody:
        return cls(
            role_id=ref.role_uuid,
            job_posting_id=ref.opening_uuid,
            private_job_posting_id=ref.own_posting_uuid,
        )


class TargetFields(RequestModel):
    """A request aimed at a Target: a role and optionally one opening in it,
    or a posting of the user's own. Anything else is refused as invalid."""

    role_id: uuid.UUID | None = None
    job_posting_id: uuid.UUID | None = None
    private_job_posting_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _one_shape(self) -> Self:
        if (self.role_id is None) == (self.private_job_posting_id is None):
            raise ValueError("a target is a role, or a posting of your own: exactly one")
        if self.job_posting_id is not None and self.role_id is None:
            raise ValueError("an opening is aimed at inside its role")
        return self

    def ref(self) -> TargetRef:
        return TargetRef.of(self.role_id, self.job_posting_id, self.private_job_posting_id)


class OwnPostingRequest(RequestModel):
    """A posting of the user's own (Phase 8): a title, optionally a company,
    and the job description, which stays private to the user."""

    title: str = Field(min_length=1, max_length=MAX_TITLE)
    company_name: str | None = Field(default=None, max_length=MAX_COMPANY_NAME)
    job_description: str = Field(min_length=1, max_length=MAX_JOB_DESCRIPTION)


class OwnPostingUploadEstimateRequest(RequestModel):
    """A posting of the user's own to be uploaded as a file: priced before the
    file is read, so only its title and company are known."""

    title: str = Field(min_length=1, max_length=MAX_TITLE)
    company_name: str | None = Field(default=None, max_length=MAX_COMPANY_NAME)


class OwnPostingEstimate(ApiModel):
    """What reading and scoring a posting of the user's own costs, shown
    before anything runs: two calls to add one, one to rescore it."""

    cost_usd: str
    model_id: str | None
    rate_is_published: bool | None = None


class OwnPosting(ApiModel):
    """A posting the user brought themselves, to aim the Advisor at. Never on
    the role map."""

    private_job_posting_id: uuid.UUID
    title: str
    company_name: str
    # How its JD arrived; an uploaded one names its file.
    source: Literal["pasted", "uploaded"]
    filename: str | None
    # The latest run reading and scoring it; null before any.
    status: Literal["running", "ready", "failed"] | None
    error_code: str | None
    error_message: str | None
    fit: int | None
    # Scored against an analysis older than the latest: worth rescoring.
    is_stale: bool
    scored_at: Timestamp | None

    @classmethod
    def from_view(cls, posting: OwnPostingView) -> OwnPosting:
        return cls(
            private_job_posting_id=posting.private_job_posting_id,
            title=posting.title,
            company_name=posting.company_name,
            source=posting.source,
            filename=posting.filename,
            status=posting.status,
            error_code=posting.error_code,
            error_message=posting.error_message,
            fit=posting.fit,
            is_stale=posting.is_stale,
            scored_at=posting.scored_at,
        )


class OwnPostingPage(Page[OwnPosting]):
    pass
