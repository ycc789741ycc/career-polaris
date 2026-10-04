"""The limit past which running work reads as lost counts only while the
process that runs it is up (ADR 0052)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from advisor.activity.domain import Staleness

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
LIMIT = Staleness(timedelta(minutes=15))


def test_work_past_the_limit_while_the_worker_was_up_is_stale() -> None:
    started = NOW - timedelta(minutes=16)
    assert LIMIT.is_stale(started, now=NOW, online_since=NOW - timedelta(days=1))


def test_work_within_the_limit_is_not_stale() -> None:
    started = NOW - timedelta(minutes=14)
    assert not LIMIT.is_stale(started, now=NOW, online_since=NOW - timedelta(days=1))


def test_nothing_is_stale_while_the_worker_is_away() -> None:
    started = NOW - timedelta(days=3)
    assert not LIMIT.is_stale(started, now=NOW, online_since=None)


def test_the_limit_counts_from_the_later_of_the_start_and_the_return() -> None:
    started = NOW - timedelta(days=3)
    assert not LIMIT.is_stale(started, now=NOW, online_since=NOW - timedelta(minutes=14))
    assert LIMIT.is_stale(started, now=NOW, online_since=NOW - timedelta(minutes=16))
