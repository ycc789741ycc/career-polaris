"""A build's wait for the market runs out only while the crawler is up
(ADR 0027, ADR 0052)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from advisor.rolemap.domain import BuildRun

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
DEADLINE = timedelta(minutes=5)


def _waiting(asked: datetime) -> BuildRun:
    build = BuildRun.requested(owner_id=uuid.uuid4(), at=asked, wait=True)
    build.wait_for_market(needed=(uuid.uuid4(),), due=(uuid.uuid4(),), locations=(), at=asked)
    return build


def test_the_wait_runs_out_at_the_deadline_while_the_crawler_is_up() -> None:
    build = _waiting(NOW - timedelta(minutes=6))
    assert build.is_market_wait_over(
        NOW, deadline=DEADLINE, crawler_online_since=NOW - timedelta(days=1)
    )


def test_the_wait_does_not_run_out_while_the_crawler_is_away() -> None:
    build = _waiting(NOW - timedelta(days=2))
    assert not build.is_market_wait_over(NOW, deadline=DEADLINE, crawler_online_since=None)


def test_the_wait_counts_from_when_the_crawler_came_back() -> None:
    build = _waiting(NOW - timedelta(days=2))
    back = NOW - timedelta(minutes=4)
    assert not build.is_market_wait_over(NOW, deadline=DEADLINE, crawler_online_since=back)
    assert build.is_market_wait_over(
        NOW + timedelta(minutes=1), deadline=DEADLINE, crawler_online_since=back
    )
