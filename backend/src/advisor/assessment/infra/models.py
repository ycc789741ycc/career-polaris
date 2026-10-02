"""Tables in the ``assessment`` schema. Owner-zone, under RLS.

Assessments and scores are **immutable snapshots**. Each records the profile
version, model id and template version it came from, so a saved result can say
what it was based on and a stale one can be detected (domain section 2.4).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from kernel.db.base import Base, OwnedMixin, TimestampMixin, new_id


class SkillDimension(Base, OwnedMixin, TimestampMixin):
    """One axis of *this user's* skills. There is no global taxonomy.

    ``key`` is the stable id reused across re-assessments; without it, progress
    could not be shown by comparing two assessments.
    """

    __tablename__ = "skill_dimension"
    __table_args__ = (
        UniqueConstraint("owner_id", "key", name="uq_skill_dimension_owner_id"),
        {"schema": "assessment"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    short_name: Mapped[str] = mapped_column(String(32), nullable=False)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SkillAssessment(Base, OwnedMixin):
    __tablename__ = "skill_assessment"
    __table_args__ = (
        Index("ix_skill_assessment_owner_created", "owner_id", "created_at"),
        {"schema": "assessment"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    profile_version: Mapped[int] = mapped_column(Integer, nullable=False)
    model_id: Mapped[str] = mapped_column(String(128), nullable=False)
    template_version: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class DimensionScore(Base, OwnedMixin):
    __tablename__ = "dimension_score"
    __table_args__ = (
        UniqueConstraint("assessment_id", "dimension_key", name="uq_dimension_score_assessment_id"),
        {"schema": "assessment"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assessment.skill_assessment.id", ondelete="CASCADE"), nullable=False
    )
    dimension_key: Mapped[str] = mapped_column(String(64), nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    read: Mapped[str] = mapped_column(Text, nullable=False)
    # Evidence ids, each verified to belong to this user before the row exists.
    evidence_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)


class DimensionLineage(Base, OwnedMixin):
    """Added, renamed and merged, so radar history still lines up."""

    __tablename__ = "dimension_lineage"
    __table_args__ = ({"schema": "assessment"},)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assessment.skill_assessment.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    dimension_key: Mapped[str] = mapped_column(String(64), nullable=False)
    from_keys: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default="[]")
    previous_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AnalysisRun(Base, OwnedMixin):
    """One background analysis (ADR 0006, ADR 0018).

    The row exists before the job runs, so the page can show the analysis
    running, a role map can wait for it, and a failure has somewhere to go.
    """

    __tablename__ = "analysis_run"
    __table_args__ = (
        CheckConstraint("status IN ('running', 'ready', 'failed')", name="status"),
        Index("ix_analysis_run_owner_started", "owner_id", "started_at"),
        {"schema": "assessment"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
