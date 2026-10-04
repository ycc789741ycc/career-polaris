"""The arithmetic of a fixed window, and how a refusal says when (ADR 0054)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from kernel.limits import Limit, get_wait_label, get_window_start


def test_a_day_window_starts_at_midnight_utc() -> None:
    now = datetime(2026, 10, 5, 17, 30, tzinfo=UTC)
    assert get_window_start(now, timedelta(days=1)) == datetime(2026, 10, 5, tzinfo=UTC)


def test_an_hour_window_starts_on_the_hour() -> None:
    now = datetime(2026, 10, 5, 17, 59, 59, tzinfo=UTC)
    assert get_window_start(now, timedelta(hours=1)) == datetime(2026, 10, 5, 17, tzinfo=UTC)


@pytest.mark.parametrize(
    ("seconds", "label"),
    [
        (1, "a minute"),
        (60, "a minute"),
        (61, "2 minutes"),
        (3599, "60 minutes"),
        (3600, "an hour"),
        (3601, "2 hours"),
        (23 * 3600, "23 hours"),
    ],
)
def test_the_wait_is_said_in_whole_units_rounded_up(seconds: int, label: str) -> None:
    assert get_wait_label(seconds) == label


def test_a_limit_allows_at_least_one_attempt() -> None:
    with pytest.raises(ValueError, match="at least one"):
        Limit("uploads", 0, timedelta(days=1), "No.")


def test_a_window_longer_than_the_counters_are_kept_is_refused() -> None:
    """Counters are swept after a week; a longer window would forget early."""
    with pytest.raises(ValueError, match="window"):
        Limit("uploads", 5, timedelta(days=30), "No.")
