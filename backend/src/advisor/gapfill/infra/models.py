"""Tables in the ``gapfill`` schema. Owner-zone, under RLS.

A question set is keyed on its Target — a role, and optionally one opening in
it (ADR 0022) — and records the gaps it was written for, the model, and a
status the page polls (ADR 0006). Answers are not stored here while the user
types: they arrive in one submit and are written as ``profile.evidence`` with
source ``user_answer``; each question keeps the evidence id it became.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
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


class QuestionSet(Base, OwnedMixin):
    __tablename__ = "question_set"
    __table_args__ = (
        CheckConstraint(
            "status IN ('writing', 'ready', 'failed', 'superseded', 'cancelled')", name="status"
        ),
        CheckConstraint("num_nonnulls(role_id, private_job_posting_id) = 1", name="target"),
        Index("ix_question_set_owner_created", "owner_id", "created_at"),
        {"schema": "gapfill"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    # The Target (ADR 0022): a role and optionally one opening in it, or a
    # posting of the user's own (Phase 8); exactly one of the two.
    role_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    job_posting_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    private_job_posting_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    # "{role} · {company}", kept so the set reads without the Target.
    label: Mapped[str] = mapped_column(String(400), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    # The gaps asked about: [{key, label, status, lift}], costliest first.
    gaps: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=sql_text("'[]'::jsonb")
    )
    model_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    template_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    written_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Where writing it has got (ADR 0042).
    stage: Mapped[str | None] = mapped_column(String(24), nullable=True)
    progress: Mapped[float] = mapped_column(Float, nullable=False, server_default="0")
    estimated_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)


class Question(Base, OwnedMixin):
    __tablename__ = "question"
    __table_args__ = (
        CheckConstraint("answer_type IN ('choice', 'free_text', 'both')", name="answer_type"),
        CheckConstraint("gap_status IN ('partial', 'no_evidence')", name="gap_status"),
        {"schema": "gapfill"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    set_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("gapfill.question_set.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    gap_key: Mapped[str] = mapped_column(String(128), nullable=False)
    gap_label: Mapped[str] = mapped_column(String(400), nullable=False)
    gap_status: Mapped[str] = mapped_column(String(16), nullable=False)
    lift: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    asked_because: Mapped[str] = mapped_column(Text, nullable=False)
    answer_type: Mapped[str] = mapped_column(String(16), nullable=False)
    choices: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=sql_text("'[]'::jsonb")
    )
    # The profile evidence the submitted answer became.
    evidence_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
