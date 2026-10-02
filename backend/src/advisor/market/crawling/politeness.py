"""Crawler hygiene: robots.txt, rate limits, and an identifying user agent.

This is infrastructure, not domain logic, but it is required. We crawl only
sources that permit it, and we behave on them (domain section 2.5).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from kernel.errors import RateLimitedError

# How long a host is left alone after its first 429 or 403 with no
# Retry-After; each one in a row doubles it, up to the cap.
FIRST_BACKOFF_SECONDS = 15 * 60
MAX_BACKOFF_SECONDS = 6 * 60 * 60
# How long a host's robots.txt is trusted before it is read again.
ROBOTS_TTL_SECONDS = 24 * 60 * 60


@dataclass
class RateLimiter:
    """At most ``per_second`` requests to any one host."""

    per_second: float
    _last_call: dict[str, float] = field(default_factory=dict)

    async def wait(self, url: str) -> None:
        if self.per_second <= 0:
            return
        host = urlsplit(url).hostname or ""
        interval = 1.0 / self.per_second
        now = time.monotonic()
        earliest = self._last_call.get(host, 0.0) + interval
        if now < earliest:
            await asyncio.sleep(earliest - now)
        self._last_call[host] = time.monotonic()


class RobotsCache:
    """Remembers each host's robots.txt for ``ttl_seconds``.

    The crawler looks for due sources every few seconds (ADR 0027), so the
    cache outlives a single run: reading robots.txt on every look would be
    the busiest thing we ever did to a host.
    """

    def __init__(
        self,
        user_agent: str,
        *,
        ttl_seconds: float = ROBOTS_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._user_agent = user_agent
        self._ttl = ttl_seconds
        self._clock = clock
        self._parsers: dict[str, tuple[RobotFileParser | None, float]] = {}

    def remember(self, origin: str, robots_txt: str | None) -> None:
        if robots_txt is None:
            # No robots.txt means nothing is disallowed.
            self._parsers[origin] = (None, self._clock())
            return
        parser = RobotFileParser()
        parser.parse(robots_txt.splitlines())
        self._parsers[origin] = (parser, self._clock())

    def knows(self, origin: str) -> bool:
        known = self._parsers.get(origin)
        return known is not None and self._clock() - known[1] < self._ttl

    def allows(self, url: str) -> bool:
        known = self._parsers.get(origin_of(url))
        parser = known[0] if known is not None else None
        return True if parser is None else bool(parser.can_fetch(self._user_agent, url))


class HostGuard:
    """What the crawler owes each host beyond robots.txt and the rate limit
    (ADR 0027): a pause after it says no, and a daily ceiling.

    * A 429 or 403 pauses the host until its ``Retry-After``, or for a backoff
      that doubles with each one in a row, from 15 minutes up to six hours.
    * At most ``max_per_day`` requests reach one host in one UTC day, however
      many builds are waiting.

    A source on a paused or spent host is skipped, not failed: it stays due,
    and the builds waiting for it start at their deadline on what is stored.
    """

    def __init__(
        self,
        *,
        max_per_day: int,
        clock: Callable[[], datetime],
    ) -> None:
        self._max_per_day = max_per_day
        self._clock = clock
        self._paused_until: dict[str, datetime] = {}
        self._refusals: dict[str, int] = {}
        self._counts: dict[tuple[str, date], int] = {}

    def check(self, url: str) -> None:
        """Raise ``RateLimitedError`` when this host may not be asked now."""
        host = host_of(url)
        now = self._clock()
        until = self._paused_until.get(host)
        if until is not None and now < until:
            raise RateLimitedError("host paused after refusing us", host=host, until=until)
        if self._counts.get((host, now.date()), 0) >= self._max_per_day:
            raise RateLimitedError("daily request ceiling reached for host", host=host)

    def count(self, url: str) -> None:
        """One request is about to reach this host."""
        key = (host_of(url), self._clock().date())
        self._counts[key] = self._counts.get(key, 0) + 1

    def refused(self, url: str, retry_after: str | None) -> datetime:
        """The host answered 429 or 403: pause it. Returns until when."""
        host = host_of(url)
        now = self._clock()
        refusals = self._refusals.get(host, 0) + 1
        self._refusals[host] = refusals
        wait = _retry_after_seconds(retry_after, now)
        if wait is None:
            wait = min(FIRST_BACKOFF_SECONDS * 2 ** (refusals - 1), MAX_BACKOFF_SECONDS)
        until = datetime.fromtimestamp(now.timestamp() + wait, tz=now.tzinfo)
        self._paused_until[host] = until
        return until

    def answered(self, url: str) -> None:
        """The host answered normally: its backoff starts over next time."""
        self._refusals.pop(host_of(url), None)


def _retry_after_seconds(value: str | None, now: datetime) -> float | None:
    """A ``Retry-After`` header as seconds from now: delay-seconds or an
    HTTP date. ``None`` when there is none or it can't be read."""
    if not value:
        return None
    text = value.strip()
    if text.isdigit():
        return float(text)
    try:
        return max(0.0, (parsedate_to_datetime(text) - now).total_seconds())
    except (TypeError, ValueError):
        return None


def host_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def origin_of(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def robots_url_for(url: str) -> str:
    return f"{origin_of(url)}/robots.txt"
