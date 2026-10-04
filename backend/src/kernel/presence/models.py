"""One row per running worker or crawler process, refreshed by its heartbeat."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from kernel.db.base import Base


class ProcessHeartbeat(Base):
    __tablename__ = "process"
    __table_args__ = (
        Index("ix_process_unit_seen_at", "unit", "seen_at"),
        {"schema": "presence"},
    )

    # Chosen by the process when it starts: a restart is a new row.
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    unit: Mapped[str] = mapped_column(String(16), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
