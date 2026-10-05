"""One row per thing limited, per subject, per window: how often it happened."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String
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
