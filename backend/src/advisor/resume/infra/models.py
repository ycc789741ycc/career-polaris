"""Tables in the ``resume`` schema. Owner-zone, under RLS.

A résumé aims at one Target and stores its frozen snapshot, like a gap plan.
Its content lives in versions, never overwritten: generated, saved by hand, or
applied from the revision chat. Each revision exchange is kept with the edit it
proposed, and each export with where its PDF went.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from kernel.db.base import Base, OwnedMixin, new_id


class Resume(Base, OwnedMixin):
    __tablename__ = "resume"
    __table_args__ = (
        CheckConstraint("status IN ('drafting', 'ready', 'failed', 'filling')", name="status"),
        CheckConstraint("template IN ('organic', 'plain')", name="template"),
        CheckConstraint("num_nonnulls(role_id, private_job_posting_id) = 1", name="target"),
        Index("ix_resume_owner_updated", "owner_id", "updated_at"),
        {"schema": "resume"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    # The Target (ADR 0022): a role and optionally one opening in it, or a
    # posting of the user's own (Phase 8); exactly one of the two.
    role_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    job_posting_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    private_job_posting_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    target_label: Mapped[str] = mapped_column(String(400), nullable=False)
    snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # RequirementCoverage for the snapshot: [{requirement, verdict, dimension_key,
    # evidence: [{id, reference, fact}]}].
    coverage: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=sql_text("'[]'::jsonb")
    )
    template: Mapped[str] = mapped_column(String(16), nullable=False)
    options: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # What the latest generated version read (ADR 0035). None before the
    # first write, and on résumés written before they were recorded.
    profile_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # The sections every new version is written to, in order: [{kind, title}]
    # (ADR 0039).
    section_plan: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=sql_text(
            """'[{"kind": "summary", "title": null}, {"kind": "experience", "title": null},"""
            """ {"kind": "skills", "title": null}]'::jsonb"""
        ),
    )


class ResumeVersion(Base, OwnedMixin):
    __tablename__ = "version"
    __table_args__ = (
        CheckConstraint("source IN ('generated', 'manual', 'chat', 'answers')", name="source"),
        Index("ix_version_resume_number", "resume_id", "number", unique=True),
        {"schema": "resume"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    resume_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("resume.resume.id", ondelete="CASCADE"), nullable=False
    )
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    # ResumeContent.to_dict().
    content: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    # Set for generated and chat versions; a manual save has no model.
    model_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    template_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Revision(Base, OwnedMixin):
    """One exchange in the revision chat: the request, the reply, the edit."""

    __tablename__ = "revision"
    __table_args__ = (
        Index("ix_revision_resume_created", "resume_id", "created_at"),
        {"schema": "resume"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    resume_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("resume.resume.id", ondelete="CASCADE"), nullable=False
    )
    request: Mapped[str] = mapped_column(Text, nullable=False)
    reply: Mapped[str] = mapped_column(Text, nullable=False)
    # The proposed content, validated; null when the model only advised.
    proposal: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    applied_version_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    model_id: Mapped[str] = mapped_column(String(128), nullable=False)
    template_version: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Export(Base, OwnedMixin):
    __tablename__ = "export"
    __table_args__ = (
        CheckConstraint("status IN ('rendering', 'ready', 'failed')", name="status"),
        {"schema": "resume"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("resume.version.id", ondelete="CASCADE"), nullable=False, index=True
    )
    template: Mapped[str] = mapped_column(String(16), nullable=False)
    # Cut to one page or not, read when Export was clicked (ADR 0038). None on
    # exports from before it was kept, which are never reused.
    trim: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    storage_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
