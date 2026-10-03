"""Tables in the ``target`` schema. Owner-zone, under RLS (ADR 0033).

A posting of the user's own and what was made of it: the JD they brought, the
runs that read and scored it, its requirements, the AI's evaluation of them
and the fit worked out from it. The crawler has no grant on this schema, so a
JD stored here cannot reach anyone else, however a query is written.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from kernel.db.base import Base, OwnedMixin, new_id

_POSTING = "target.private_job_posting.id"


class PrivateJobPosting(Base, OwnedMixin):
    """A posting of the user's own: the JD they brought. Used only for its
    owner, and never by a build."""

    __tablename__ = "private_job_posting"
    __table_args__ = (
        CheckConstraint("source IN ('pasted', 'uploaded', 'filled_in')", name="source"),
        # Only an uploaded file waits for its JD to be read, and only a role
        # filled in by hand with nothing listed has none at all (ADR 0034).
        CheckConstraint(
            "job_description IS NOT NULL"
            " OR (source = 'uploaded' AND storage_key IS NOT NULL)"
            " OR (source = 'filled_in' AND has_estimated_requirements)",
            name="job_description",
        ),
        Index("ix_private_job_posting_owner_created", "owner_id", "created_at"),
        {"schema": "target"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    company_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # None for an uploaded file until the worker has read it.
    job_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pasted")
    filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # The uploaded file in object storage, until it has been read.
    storage_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Named after its file until the file is read (ADR 0034).
    has_placeholder_title: Mapped[bool] = mapped_column(nullable=False, server_default="false")
    # Filled in with nothing listed: what it asks for is estimated (ADR 0034).
    has_estimated_requirements: Mapped[bool] = mapped_column(nullable=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PostingEvaluation(Base, OwnedMixin):
    """One run reading and scoring a posting of the user's own, recorded
    before it is queued so the Advisor can poll it (ADR 0006)."""

    __tablename__ = "posting_evaluation"
    __table_args__ = (
        CheckConstraint("status IN ('running', 'ready', 'failed')", name="status"),
        Index(
            "ix_posting_evaluation_owner_posting",
            "owner_id",
            "private_job_posting_id",
            "requested_at",
        ),
        {"schema": "target"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    private_job_posting_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(_POSTING, ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    # False for a rescore, which keeps the requirements already read.
    reads_requirements: Mapped[bool] = mapped_column(nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PostingRequirement(Base, OwnedMixin):
    """Free text read out of a posting of the user's own. It has no dimension."""

    __tablename__ = "posting_requirement"
    __table_args__ = ({"schema": "target"},)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    private_job_posting_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(_POSTING, ondelete="CASCADE"), nullable=False, index=True
    )
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    weight: Mapped[float] = mapped_column(Float, nullable=False)
    expected_level: Mapped[str] = mapped_column(String(32), nullable=False)


class PostingRequirementFit(Base, OwnedMixin):
    """The AI's evaluation of a posting of the user's own: its requirements
    mapped onto the user's dimensions, with targets. Every one taken is kept;
    the newest per posting is the current one."""

    __tablename__ = "posting_requirement_fit"
    __table_args__ = (
        Index(
            "ix_posting_requirement_fit_owner_posting",
            "owner_id",
            "private_job_posting_id",
            "created_at",
        ),
        {"schema": "target"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    private_job_posting_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(_POSTING, ondelete="CASCADE"), nullable=False
    )
    assessment_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    # [{statement, weight, expected_level}], as scored.
    requirements: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    requirement_map: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    target_profile: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    reasoning: Mapped[str] = mapped_column(Text, nullable=False)
    model_id: Mapped[str] = mapped_column(String(128), nullable=False)
    template_version: Mapped[str] = mapped_column(String(128), nullable=False)
    # A hash of what it read, as on rolemap.role_fit.
    requirements_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class OwnPostingFit(Base, OwnedMixin):
    """The user's fit to a posting of their own, worked out locally from a
    posting_requirement_fit; never an AI call. Every one is kept, the newest
    current."""

    __tablename__ = "own_posting_fit"
    __table_args__ = (
        Index(
            "ix_own_posting_fit_owner_posting",
            "owner_id",
            "private_job_posting_id",
            "created_at",
        ),
        {"schema": "target"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    private_job_posting_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(_POSTING, ondelete="CASCADE"), nullable=False
    )
    # The posting_requirement_fit it was worked out from.
    source_fit_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("target.posting_requirement_fit.id", ondelete="CASCADE"), nullable=False
    )
    assessment_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    requirements: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    requirement_map: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    target_profile: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    gaps: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    uncovered: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
