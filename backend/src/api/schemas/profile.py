"""Profile's wire shapes: connectors, uploaded résumés, evidence and the profile."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date
from typing import Literal

from pydantic import Field

from advisor.profile import ConnectionView, EvidenceView, ProfileSnapshot, ResumeFileView
from api.schemas.common import ApiModel, RequestModel, Timestamp


class CallbackRequest(RequestModel):
    code: str = Field(min_length=1)
    state: str = Field(min_length=1)


class Connection(ApiModel):
    """One connector, whether or not the user has connected it."""

    kind: str
    connected: bool
    account: str | None
    # `disconnected` until the user connects it.
    status: str
    last_synced_at: Timestamp | None
    last_error: str | None
    # What the connector asks for, in words the consent screen shows.
    scopes: list[str]

    @classmethod
    def from_view(
        cls, kind: str, connection: ConnectionView | None, scopes: Sequence[str]
    ) -> Connection:
        return cls(
            kind=kind,
            connected=connection is not None,
            account=connection.account if connection is not None else None,
            status=connection.status if connection is not None else "disconnected",
            last_synced_at=connection.last_synced_at if connection is not None else None,
            last_error=connection.last_error if connection is not None else None,
            scopes=list(scopes),
        )


class AuthorizationUrl(ApiModel):
    url: str


class ConnectionResult(ApiModel):
    kind: str
    status: str

    @classmethod
    def from_view(cls, connection: ConnectionView) -> ConnectionResult:
        return cls(kind=connection.kind, status=connection.status)


class ResumeUpload(ApiModel):
    id: uuid.UUID
    filename: str
    # Parsing happens on the worker, never in the request.
    status: Literal["parsing"] = "parsing"

    @classmethod
    def from_view(cls, resume: ResumeFileView) -> ResumeUpload:
        return cls(id=resume.id, filename=resume.filename)


class ResumeFile(ApiModel):
    id: uuid.UUID
    filename: str
    status: str
    parse_error: str | None
    uploaded_at: Timestamp

    @classmethod
    def from_view(cls, resume: ResumeFileView) -> ResumeFile:
        return cls(
            id=resume.id,
            filename=resume.filename,
            status=resume.status,
            parse_error=resume.parse_error,
            uploaded_at=resume.uploaded_at,
        )


class DownloadUrl(ApiModel):
    """Short-lived and signed: an upload is never publicly addressable."""

    url: str


class Evidence(ApiModel):
    id: uuid.UUID
    source: str
    reference: str
    fact: str
    observed_on: date | None
    confidence: float
    # One piece of work, or a tally over many ("12 merged pull requests").
    granularity: Literal["item", "summary"]
    # How many items a summary counts; null on an item.
    tally: int | None
    # The repository or project the work belongs to, when there is one.
    subject: str | None

    @classmethod
    def from_view(cls, evidence: EvidenceView) -> Evidence:
        return cls(
            id=evidence.id,
            source=str(evidence.source),
            reference=evidence.reference,
            fact=evidence.fact,
            observed_on=evidence.observed_on,
            confidence=evidence.confidence,
            granularity=str(evidence.granularity),
            tally=evidence.tally,
            subject=evidence.subject,
        )


class Position(ApiModel):
    title: str
    company: str
    started_on: date
    ended_on: date | None


class Profile(ApiModel):
    """The profile's headline numbers and career timeline."""

    version: int
    evidence_count: int
    total_experience_months: int
    positions: list[Position]

    @classmethod
    def from_view(cls, snapshot: ProfileSnapshot) -> Profile:
        return cls(
            version=snapshot.version,
            evidence_count=len(snapshot.evidence),
            total_experience_months=snapshot.total_experience_months,
            positions=[
                Position(
                    title=p.title,
                    company=p.company,
                    started_on=p.started_on,
                    ended_on=p.ended_on,
                )
                for p in snapshot.positions
            ],
        )
