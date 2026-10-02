"""When recorded background work stops counting as running.

A job records itself as running before it is queued, and records how it ended
when it ends (ADR 0006). A worker killed mid-job never records the end, so
without a limit the row would say "running" forever and block every stage
after it. Past the limit it is reported as lost instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True, slots=True)
class Staleness:
    """How long work may show as running before it is treated as lost."""

    limit: timedelta

    def is_stale(self, started_at: datetime, *, now: datetime) -> bool:
        return now - started_at > self.limit
