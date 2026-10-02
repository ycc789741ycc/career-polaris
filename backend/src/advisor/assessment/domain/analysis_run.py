"""One request to analyse a user's evidence, recorded before it is queued
(ADR 0006, ADR 0018).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class AnalysisRunStatus(StrEnum):
    """An analysis runs in the background, so it is recorded before it starts
    and the page polls it (ADR 0006, ADR 0018)."""

    RUNNING = "running"
    READY = "ready"
    FAILED = "failed"


@dataclass(slots=True)
class AnalysisRun:
    """One request to analyse this user's evidence. The assessment it writes
    is a separate snapshot; this only says whether it is still being made, and
    why it could not be."""

    id: uuid.UUID
    owner_id: uuid.UUID
    status: AnalysisRunStatus
    started_at: datetime
    finished_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None

    @classmethod
    def requested(cls, *, owner_id: uuid.UUID, at: datetime) -> AnalysisRun:
        return cls(
            id=uuid.uuid4(), owner_id=owner_id, status=AnalysisRunStatus.RUNNING, started_at=at
        )

    @property
    def is_running(self) -> bool:
        return self.status is AnalysisRunStatus.RUNNING

    def ready(self, at: datetime) -> None:
        self.status = AnalysisRunStatus.READY
        self.finished_at = at

    def failed(self, *, code: str, message: str, at: datetime) -> None:
        self.status = AnalysisRunStatus.FAILED
        self.error_code = code
        self.error_message = message
        self.finished_at = at
