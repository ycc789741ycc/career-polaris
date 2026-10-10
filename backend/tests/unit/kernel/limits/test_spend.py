"""The spend meter's rules that need no database: windows and what is left."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from kernel.errors import PlatformAiQuotaReachedError
from kernel.limits import Charge, SpendLimit, SpendState, SpendWindow, get_spend_window_start


def test_a_day_starts_at_midnight_utc_whatever_the_clock_says() -> None:
    taipei = timezone(timedelta(hours=8))
    now = datetime(2026, 10, 11, 3, 30, tzinfo=taipei)  # 19:30 UTC on the 10th

    assert get_spend_window_start(now, SpendWindow.DAY) == datetime(2026, 10, 10, tzinfo=UTC)


def test_a_month_starts_on_the_first_at_midnight_utc() -> None:
    now = datetime(2026, 10, 31, 23, 59, tzinfo=UTC)

    assert get_spend_window_start(now, SpendWindow.MONTH) == datetime(2026, 10, 1, tzinfo=UTC)


def test_what_is_left_takes_out_both_spend_and_reservations() -> None:
    state = SpendState(
        allowed_usd=Decimal("2"), spent_usd=Decimal("1.25"), reserved_usd=Decimal("0.5")
    )
    assert state.remaining_usd == Decimal("0.25")

    over = SpendState(allowed_usd=Decimal("2"), spent_usd=Decimal("2.10"), reserved_usd=Decimal(0))
    assert over.remaining_usd == Decimal(0)


def test_a_limit_must_allow_something() -> None:
    with pytest.raises(ValueError, match="allow"):
        SpendLimit("x", Decimal(0), SpendWindow.DAY, PlatformAiQuotaReachedError, "No.")


def test_a_charge_is_kept_as_a_digest_of_its_limit_and_subject() -> None:
    limit = SpendLimit("x", Decimal(1), SpendWindow.DAY, PlatformAiQuotaReachedError, "No.")
    digest = Charge(limit, "account-1").get_digest()

    assert len(digest) == 64 and "account-1" not in digest
    assert digest != Charge(limit, "account-2").get_digest()
