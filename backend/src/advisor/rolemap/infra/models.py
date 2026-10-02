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
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from kernel.db.base import Base, OwnedMixin, TimestampMixin, new_id


class Role(Base, OwnedMixin, TimestampMixin):
    """A group of openings in one user's target locations, and what they ask
    for.

    ``id`` is stable across re-clustering: goals and fits point at it, so
    renumbering on every crawl would break them.
    """

    __tablename__ = "role"
    __table_args__ = (
        Index("ix_role_owner_name", "owner_id", "name"),
        {"schema": "rolemap"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
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
    (ADR 0024): the query a build searches and matches with. Replaced as a set
    by each analysis; what a build made of it is a ``candidate_placement``."""

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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CandidatePlacement(Base, OwnedMixin):
    """What one build made of one candidate: the role it became, or why none
    (Phase 8). Kept per build, with the candidate's rank and title copied in,
    so it still reads after the next analysis replaces the candidates."""

    __tablename__ = "candidate_placement"
    __table_args__ = (
        CheckConstraint(
            "outcome IN ('placed', 'outside_top_k', 'too_few_openings')", name="outcome"
        ),
        CheckConstraint("(outcome = 'placed') = (role_id IS NOT NULL)", name="role"),
        UniqueConstraint(
            "build_run_id", "candidate_id", name="uq_candidate_placement_build_run_id"
        ),
        {"schema": "rolemap"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    build_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("rolemap.build_run.id", ondelete="CASCADE"), nullable=False, index=True
    )
    candidate_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("rolemap.role_candidate.id", ondelete="SET NULL"), nullable=True, index=True
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    outcome: Mapped[str] = mapped_column(String(24), nullable=False)
    role_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("rolemap.role.id", ondelete="SET NULL"), nullable=True
    )
    opening_count: Mapped[int] = mapped_column(Integer, nullable=False)
    # The local estimate that chose the k (ADR 0027); not a fit.
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
    # What the weight came from; the fit is scored against these (ADR 0028).
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class RoleFit(Base, OwnedMixin):
    """A snapshot of fit between this user and one of their roles (ADR 0028).

    Fit lives here, on the User x Role pair, never as an attribute of a role.
    Every fit taken is kept; the newest per role is the current one.
    """

    __tablename__ = "role_fit"
    __table_args__ = (
        Index("ix_role_fit_owner_role", "owner_id", "role_id", "created_at"),
        {"schema": "rolemap"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    # The analysis whose scores the fit was taken against.
    assessment_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    role_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    # The projection is an AI judgement, so it is stored with its reasoning and
    # shown to the user.
    reasoning: Mapped[str] = mapped_column(Text, nullable=False)
    target_profile: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    gaps: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    uncovered: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    # What the fit was projected from, so it can be re-read later without the
    # role: [{statement, weight, expected_level}].
    requirements: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    # Requirement statement -> the user's dimension key it maps to, or null.
    requirement_map: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    model_id: Mapped[str] = mapped_column(String(128), nullable=False)
    template_version: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PostingEvaluation(Base, OwnedMixin):
    """One run reading and scoring a posting of the user's own (Phase 8),
    recorded before it is queued so the Advisor can poll it (ADR 0006)."""

    __tablename__ = "posting_evaluation"
    __table_args__ = (
        CheckConstraint("status IN ('running', 'ready', 'failed')", name="status"),
        Index(
            "ix_posting_evaluation_owner_posting",
            "owner_id",
            "private_job_posting_id",
            "requested_at",
        ),
        {"schema": "rolemap"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    # The pasted JD, in market_user.private_job_posting. No foreign key: the
    # schemas belong to different components.
    private_job_posting_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
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
    __table_args__ = ({"schema": "rolemap"},)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    private_job_posting_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
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
        {"schema": "rolemap"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    private_job_posting_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    assessment_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    # [{statement, weight, expected_level}], as scored.
    requirements: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    requirement_map: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    target_profile: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    reasoning: Mapped[str] = mapped_column(Text, nullable=False)
    model_id: Mapped[str] = mapped_column(String(128), nullable=False)
    template_version: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PostingFit(Base, OwnedMixin):
    """The user's fit to one posting, worked out locally from an AI fit; never
    an AI call. Every one worked out is kept; the newest per posting is the
    current one."""

    __tablename__ = "posting_fit"
    __table_args__ = (
        CheckConstraint("basis IN ('own')", name="basis"),
        Index("ix_posting_fit_owner_key", "owner_id", "posting_key", "created_at"),
        {"schema": "rolemap"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    # "private:<id>" for a posting of the user's own, as role_member keys it.
    posting_key: Mapped[str] = mapped_column(String(128), nullable=False)
    basis: Mapped[str] = mapped_column(String(8), nullable=False)
    # The AI fit it was worked out from: a posting_requirement_fit for `own`.
    source_fit_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
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
