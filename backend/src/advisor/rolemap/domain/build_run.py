"""One request to rebuild a user's role map, recorded before it is queued
(ADR 0006, ADR 0018).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class BuildRunStatus(StrEnum):
    """A role-map build runs in the background, so it is recorded before it
    starts and the page polls it (ADR 0006, ADR 0018).

    ``waiting`` means it was asked for while an analysis was running, and starts
    when that analysis finishes; or that it waits for the market sources it
    needs to be fetched, and starts when they are or at its deadline (ADR
    0027).
    """

    WAITING = "waiting"
    RUNNING = "running"
    READY = "ready"
    FAILED = "failed"


@dataclass(slots=True)
class BuildRun:
    """One request to rebuild this user's role map."""

    id: uuid.UUID
    owner_id: uuid.UUID
    status: BuildRunStatus
    requested_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None
    # The market sources it reads, and those of them it waits to be fetched.
    # Ids of ownerless shared rows; never the other way round (ADR 0027).
    needed_source_ids: tuple[uuid.UUID, ...] = ()
    awaited_source_ids: tuple[uuid.UUID, ...] = ()
    # The target locations it was built for, and how old the oldest fetch it
    # read was: what the role map says it is "as of".
    locations: tuple[str, ...] = ()
    # When it asked the market; its deadline runs from here.
    awaited_since: datetime | None = None
    market_data_at: datetime | None = None

    @classmethod
    def requested(cls, *, owner_id: uuid.UUID, at: datetime, wait: bool) -> BuildRun:
        return cls(
            id=uuid.uuid4(),
            owner_id=owner_id,
            status=BuildRunStatus.WAITING if wait else BuildRunStatus.RUNNING,
            requested_at=at,
            started_at=None if wait else at,
        )

    @property
    def is_waiting(self) -> bool:
        return self.status is BuildRunStatus.WAITING

    @property
    def is_waiting_for_market(self) -> bool:
        return self.is_waiting and bool(self.awaited_source_ids)

    def wait_for_market(
        self,
        *,
        needed: tuple[uuid.UUID, ...],
        due: tuple[uuid.UUID, ...],
        locations: tuple[str, ...],
        at: datetime,
    ) -> None:
        """It has asked the market for what it reads: it waits for the due
        sources, or for nothing."""
        self.status = BuildRunStatus.WAITING
        self.needed_source_ids = needed
        self.awaited_source_ids = due
        self.locations = locations
        self.awaited_since = at

    @property
    def is_running(self) -> bool:
        return self.status is BuildRunStatus.RUNNING

    @property
    def is_open(self) -> bool:
        """Still to finish: waiting or running."""
        return self.is_waiting or self.is_running

    def start(self, at: datetime) -> None:
        if not self.is_waiting:
            raise ValueError(f"a {self.status} build cannot start")
        self.status = BuildRunStatus.RUNNING
        self.started_at = at

    def ready(self, at: datetime, *, market_data_at: datetime | None = None) -> None:
        self.status = BuildRunStatus.READY
        self.finished_at = at
        self.market_data_at = market_data_at

    def failed(self, *, code: str, message: str, at: datetime) -> None:
        self.status = BuildRunStatus.FAILED
        self.error_code = code
        self.error_message = message
        self.finished_at = at
