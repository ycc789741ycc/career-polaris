"""One row per thing limited, per subject, per window: how often it happened,
or how much it spent and holds reserved (ADR 0054, ADR 0064)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from kernel.db.base import Base


class LimitCounter(Base):
    __tablename__ = "counter"
    __table_args__ = (
        Index("ix_counter_window_start", "window_start"),
        {"schema": "limits"},
    )

    # A digest of the limit's name and its subject, never the subject itself:
    # a client's address is not kept.
    key_digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    hits: Mapped[int] = mapped_column(Integer, nullable=False)


class SpendWindowRow(Base):
    """What a subject spent in one window, in US dollars."""

    __tablename__ = "spend_window"
    __table_args__ = (
        Index("ix_spend_window_window_start", "window_start"),
        {"schema": "limits"},
    )

    key_digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    spent_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)


class SpendReservationRow(Base):
    """What a call in progress holds against one subject's window, until it
    is released or lapses."""

    __tablename__ = "spend_reservation"
    __table_args__ = (
        Index("ix_spend_reservation_key_window", "key_digest", "window_start"),
        Index("ix_spend_reservation_expires_at", "expires_at"),
        {"schema": "limits"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    key_digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    amount_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
