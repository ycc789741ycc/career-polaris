"""Tables in the ``resume`` schema. Owner-zone, under RLS.

A résumé aims at one Target and stores its frozen snapshot, like a gap plan.
Its content lives in versions, never overwritten: generated, saved by hand, or
applied from the revision chat. Each revision exchange is kept with the edit it
proposed, and each export with where its PDF went.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
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
        CheckConstraint(
            "status IN ('drafting', 'ready', 'failed', 'filling', 'cancelled')", name="status"
        ),
        CheckConstraint("template IN ('organic', 'plain')", name="template"),
        # A built-in template, or one of the user's own: exactly one (ADR 0040).
        CheckConstraint("num_nonnulls(template, custom_template_id) = 1", name="look"),
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
    template: Mapped[str | None] = mapped_column(String(16), nullable=True)
    custom_template_id: Mapped[uuid.UUID | None] = mapped_column(
        # Deleting a template moves its résumés to Organic first, in the same
        # transaction; the key refuses a delete that forgot to.
        ForeignKey("resume.custom_template.id"),
        nullable=True,
    )
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
    # The sections every new version is written to, in order, each shown or
    # hidden: [{kind, title, is_shown}] (ADR 0039, ADR 0043).
    section_plan: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=sql_text(
            """'[{"kind": "summary", "title": null, "is_shown": true},"""
            """ {"kind": "experience", "title": null, "is_shown": true},"""
            """ {"kind": "skills", "title": null, "is_shown": true},"""
            """ {"kind": "side_projects", "title": null, "is_shown": false},"""
            """ {"kind": "open_source", "title": null, "is_shown": false},"""
            """ {"kind": "education", "title": null, "is_shown": false},"""
            """ {"kind": "talks_and_writing", "title": null, "is_shown": false},"""
            """ {"kind": "certifications", "title": null, "is_shown": false}]'::jsonb"""
        ),
    )
    # Where the job running on it has got (ADR 0042).
    stage: Mapped[str | None] = mapped_column(String(24), nullable=True)
    progress: Mapped[float] = mapped_column(Float, nullable=False, server_default="0")
    estimated_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)


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
    # The built-in template; null for one of the user's own (ADR 0040).
    template: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # Cut to one page or not, read when Export was clicked (ADR 0038). None on
    # exports from before it was kept, which are never reused.
    trim: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # The look it was rendered in (ADR 0040); reuse compares it.
    spec: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    storage_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CustomTemplate(Base, OwnedMixin):
    """A résumé template of the user's own: a name and a checked spec
    (ADR 0040)."""

    __tablename__ = "custom_template"
    __table_args__ = (
        Index("ix_custom_template_owner_created", "owner_id", "created_at"),
        {"schema": "resume"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    # TemplateSpec.to_dict(), checked again whenever it is read.
    spec: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class TemplateReading(Base, OwnedMixin):
    """An upload being read for its style (ADR 0041): the draft spec and which
    values were read, and nothing of the file. Forgotten after a day."""

    __tablename__ = "template_reading"
    __table_args__ = (
        CheckConstraint("status IN ('reading', 'ready', 'failed')", name="status"),
        {"schema": "resume"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    # Where the file is until it is read; null once it is deleted.
    storage_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    spec: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    read_fields: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=sql_text("'[]'::jsonb")
    )
    defaulted_fields: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=sql_text("'[]'::jsonb")
    )
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
