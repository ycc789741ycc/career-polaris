"""A fixed-window counter per limit and subject, in Postgres.

Postgres because it is already on the edge beside the api (ADR 0051): no
cache to add, run or lose. Each attempt is one upsert in a short transaction
of its own, so an attempt that fails afterwards still counts — the limits are
against floods, not a quota of successes.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from kernel.clock import utcnow
from kernel.db import Database
from kernel.errors import RateLimitedError
from kernel.logging import get_logger

log = get_logger(__name__)

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
# Windows that ended this long ago are deleted, whoever they counted.
_KEEP = timedelta(days=7)


@dataclass(frozen=True, slots=True)
class Limit:
    """``allowed`` attempts per ``window``; ``refusal`` is what a person reads."""

    name: str
    allowed: int
    window: timedelta
    refusal: str

    def __post_init__(self) -> None:
        if self.allowed < 1:
            raise ValueError(f"limit {self.name} must allow at least one attempt")
        if not timedelta(0) < self.window <= _KEEP:
            raise ValueError(f"limit {self.name} needs a window between 0 and {_KEEP}")


def get_window_start(now: datetime, window: timedelta) -> datetime:
    """The start of the window ``now`` falls in, windows counted from the epoch."""
    elapsed = (now - _EPOCH) // window
    return _EPOCH + elapsed * window


def get_wait_label(seconds: int) -> str:
    """How long to wait, as a person says it: rounded up to a whole unit."""
    if seconds <= 60:
        return "a minute"
    if seconds < 3600:
        return f"{math.ceil(seconds / 60)} minutes"
    hours = math.ceil(seconds / 3600)
    return "an hour" if hours == 1 else f"{hours} hours"


class Limiter:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def record_attempt(self, limit: Limit, subject: str) -> None:
        """Count one attempt by ``subject``; refuse it past the limit, saying
        when to try again (``RateLimitedError``, 429 with ``Retry-After``)."""
        now = utcnow()
        start = get_window_start(now, limit.window)
        digest = hashlib.sha256(f"{limit.name}\x00{subject}".encode()).hexdigest()
        async with self._database.shared() as session:
            hits = (
                await session.execute(
                    text(
                        "INSERT INTO limits.counter (key_digest, window_start, hits) "
                        "VALUES (:key, :start, 1) "
                        "ON CONFLICT (key_digest, window_start) "
                        "DO UPDATE SET hits = limits.counter.hits + 1 "
                        "RETURNING hits"
                    ),
                    {"key": digest, "start": start},
                )
            ).scalar_one()
            # Windows long over, of any key: an index range, usually empty.
            await session.execute(
                text("DELETE FROM limits.counter WHERE window_start < :old"),
                {"old": now - 2 * _KEEP},
            )
        if hits <= limit.allowed:
            return
        wait = max(1, math.ceil((start + limit.window - now).total_seconds()))
        log.info("limits.refused", limit=limit.name, hits=hits, retry_after_seconds=wait)
        raise RateLimitedError(
            f"{limit.refusal} Try again in {get_wait_label(wait)}.",
            retry_after_seconds=wait,
        )
