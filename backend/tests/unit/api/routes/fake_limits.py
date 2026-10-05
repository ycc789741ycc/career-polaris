"""A limiter for route tests: records what was counted, refuses on request."""

from __future__ import annotations

from datetime import timedelta

from kernel.errors import RateLimitedError
from kernel.limits import Limit
from wiring.limits import Limits

LIMITS = Limits(
    signups=Limit("signups", 10, timedelta(days=1), "Too many sign-ups."),
    uploads=Limit("uploads", 30, timedelta(days=1), "Too many uploads."),
    syncs=Limit("syncs", 6, timedelta(hours=1), "Too many syncs."),
)


class FakeLimiter:
    def __init__(self) -> None:
        self.attempts: list[tuple[str, str]] = []
        self.refusing: set[str] = set()

    async def record_attempt(self, limit: Limit, subject: str) -> None:
        self.attempts.append((limit.name, subject))
        if limit.name in self.refusing:
            raise RateLimitedError(
                f"{limit.refusal} Try again in 3 hours.", retry_after_seconds=10_800
            )
