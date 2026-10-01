"""Tables in the ``rolemap`` schema.

Roles are grouped per user, over the postings in that user's target locations, and
computed on that user's key — so this is owner-zone, under RLS, even though
the postings underneath it are shared (domain decision 7).
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
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from kernel.db.base import Base, OwnedMixin, TimestampMixin, new_id


class Role(Base, OwnedMixin, TimestampMixin):
    """A cluster of postings in one user's target locations, or a role the user
    added.

    ``id`` is stable across re-clustering: goals and fits point at it, so
    renumbering on every crawl would break them.
    """

    __tablename__ = "role"
    __table_args__ = (
        Index("ix_role_owner_name", "owner_id", "name"),
        CheckConstraint("origin IN ('recommended', 'custom')", name="origin"),
        {"schema": "rolemap"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # `recommended` (one of the ten) or `custom` (added by the user, ADR 0021).
    origin: Mapped[str] = mapped_column(String(16), nullable=False, server_default="recommended")
    company_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # The custom role's pasted JD, in market_user.private_job_posting.
    private_posting_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    is_coherent: Mapped[bool] = mapped_column(nullable=False, server_default="true")
    opening_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    # Hiring bar: the bubble chart's X axis.
    hiring_bar: Mapped[int] = mapped_column(Integer, nullable=False, server_default="50")
    bar_confidence: Mapped[float] = mapped_column(Float, nullable=False, server_default="0")
    bar_basis: Mapped[str] = mapped_column(String(16), nullable=False, server_default="estimated")
    bar_sample_size: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    bar_reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Salary bands per selected market: {"Berlin": {...}, "Remote EU": {...}}.
    salary_bands: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")

    model_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    template_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RoleMember(Base, OwnedMixin):
    """Which postings a role was built from. One of the two ids is set."""

    __tablename__ = "role_member"
    __table_args__ = (
        UniqueConstraint("role_id", "posting_key", name="uq_role_member_role_id"),
        {"schema": "rolemap"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    role_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("rolemap.role.id", ondelete="CASCADE"), nullable=False
    )
    # The shared posting id, or "private:<id>" for a pasted JD. Kept as text so
    # reconciliation compares the same keys the domain works with.
    posting_key: Mapped[str] = mapped_column(String(128), nullable=False)


class RoleRequirement(Base, OwnedMixin):
    """Free text pulled from a role's postings. It has no dimension."""

    __tablename__ = "role_requirement"
    __table_args__ = ({"schema": "rolemap"},)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    role_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("rolemap.role.id", ondelete="CASCADE"), nullable=False, index=True
    )
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    weight: Mapped[float] = mapped_column(Float, nullable=False)
    expected_level: Mapped[str] = mapped_column(String(32), nullable=False)


class RoleLineage(Base, OwnedMixin):
    """Added, split, merged and retired, with parents.

    A goal pointing at a role that split needs to be able to find the successor
    with the most requirement overlap.
    """

    __tablename__ = "role_lineage"
    __table_args__ = ({"schema": "rolemap"},)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    role_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    from_role_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default="[]")
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class BuildRun(Base, OwnedMixin):
    """One background role-map build (ADR 0006, ADR 0018).

    The row exists before the job runs, and before it may start: a build asked
    for during an analysis waits here until that analysis finishes.
    """

    __tablename__ = "build_run"
    __table_args__ = (
        CheckConstraint("status IN ('waiting', 'running', 'ready', 'failed')", name="status"),
        Index("ix_build_run_owner_requested", "owner_id", "requested_at"),
        {"schema": "rolemap"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Ids of the shared crawl sources it reads and waits for (ADR 0027).
    needed_source_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default="[]")
    awaited_source_ids: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    locations: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default="[]")
    awaited_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    market_data_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RoleCandidate(Base, OwnedMixin):
    """A role the latest analysis recommended from the user's strengths
    (ADR 0024). Replaced as a set by each analysis; a build places each one on
    the role it became, or leaves ``role_id`` empty when the market lacks it."""

    __tablename__ = "role_candidate"
    __table_args__ = (
        UniqueConstraint("owner_id", "rank", name="uq_role_candidate_owner_id"),
        {"schema": "rolemap"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    # The analysis that recommended it, in assessment.skill_assessment. No
    # foreign key: the schemas belong to different components.
    assessment_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    # The user's dimension keys it rests on, checked against that analysis.
    dimension_keys: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    role_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("rolemap.role.id", ondelete="SET NULL"), nullable=True
    )
    opening_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    # The local estimate that chose the ten (ADR 0027); not a fit.
    fit_estimate: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CandidateStrength(Base, OwnedMixin):
    """One dimension as the analysis that recommended the candidates scored it,
    for the local fit estimate (ADR 0027). Replaced with the candidates."""

    __tablename__ = "candidate_strength"
    __table_args__ = (
        UniqueConstraint("owner_id", "dimension_key", name="uq_candidate_strength_owner_id"),
        {"schema": "rolemap"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    assessment_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    dimension_key: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    read: Mapped[str] = mapped_column(Text, nullable=False)
    weight: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
