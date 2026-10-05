"""When recorded background work stops counting as running.

A job records itself as running before it is queued, and records how it ended
when it ends (ADR 0006). A worker killed mid-job never records the end, so
without a limit the row would say "running" forever and block every stage
after it. Past the limit it is reported as lost instead.

The worker may run on a machine that is not always on (ADR 0051). While it is
away nothing can be lost: the work is queued, and runs when it is back. So the
limit counts only the time the worker has been up (ADR 0052).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True, slots=True)
class Staleness:
    """How long work may show as running before it is treated as lost."""

    limit: timedelta

    def is_stale(
        self, started_at: datetime, *, now: datetime, online_since: datetime | None
    ) -> bool:
        """Past the limit since it started, counting only from when the process
        that runs it last came up. ``online_since`` is None while it is away."""
        if online_since is None:
            return False
        return now - max(started_at, online_since) > self.limit
