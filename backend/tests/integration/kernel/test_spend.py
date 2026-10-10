"""The spend meter against the real database (ADR 0064). Each test meters
limits of its own, so runs never count against one another."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import text

from kernel.db import Database
from kernel.errors import PlatformAiQuotaReachedError, PlatformAiUnavailableError
from kernel.limits import Charge, SpendLimit, SpendMeter, SpendWindow

pytestmark = pytest.mark.integration

HOLD = timedelta(minutes=5)


def _limits() -> tuple[SpendLimit, SpendLimit]:
    """An account quota of $1 a month and a $1.50 day for everyone, each
    named for this test alone."""
    run = uuid.uuid4().hex
    return (
        SpendLimit(
            f"test-account-{run}",
            Decimal("1"),
            SpendWindow.MONTH,
            PlatformAiQuotaReachedError,
            "Your month is used.",
        ),
        SpendLimit(
            f"test-everyone-{run}",
            Decimal("1.50"),
            SpendWindow.DAY,
            PlatformAiUnavailableError,
            "Today is used.",
        ),
    )


@pytest_asyncio.fixture
async def metered(database: Database) -> AsyncIterator[list[Charge]]:
    """Charges a test metered; their rows are deleted afterwards."""
    charges: list[Charge] = []
    yield charges
    digests = [charge.get_digest() for charge in charges]
    async with database.shared() as session:
        for table in ("spend_reservation", "spend_window"):
            await session.execute(
                text(f"DELETE FROM limits.{table} WHERE key_digest = ANY(:digests)"),
                {"digests": digests},
            )


def _charges(
    metered: list[Charge], account: SpendLimit, everyone: SpendLimit, owner: str
) -> list[Charge]:
    charges = [Charge(account, owner), Charge(everyone, "everyone")]
    metered.extend(charges)
    return charges


async def test_a_reservation_that_fits_is_held_until_released(
    database: Database, metered: list[Charge]
) -> None:
    meter = SpendMeter(database)
    account, everyone = _limits()
    charges = _charges(metered, account, everyone, "account-a")

    held = await meter.create_reservation(charges, Decimal("0.60"), hold=HOLD)
    assert (await meter.get_state(charges[0])).reserved_usd == Decimal("0.60")
    with pytest.raises(PlatformAiQuotaReachedError, match="Your month is used"):
        await meter.create_reservation(charges, Decimal("0.60"), hold=HOLD)

    await meter.delete_reservation(held)
    assert (await meter.get_state(charges[0])).remaining_usd == Decimal("1")


async def test_settling_moves_what_was_spent_out_of_the_reservation(
    database: Database, metered: list[Charge]
) -> None:
    meter = SpendMeter(database)
    account, everyone = _limits()
    charges = _charges(metered, account, everyone, "account-a")

    held = await meter.create_reservation(charges, Decimal("0.60"), hold=HOLD)
    await meter.update_spent(held, Decimal("0.10"))
    state = await meter.get_state(charges[0])
    assert (state.spent_usd, state.reserved_usd) == (Decimal("0.10"), Decimal("0.50"))

    await meter.delete_reservation(held)
    state = await meter.get_state(charges[0])
    assert (state.spent_usd, state.reserved_usd) == (Decimal("0.10"), Decimal(0))
    assert (await meter.get_state(charges[1])).spent_usd == Decimal("0.10")


async def test_two_reservations_at_once_where_one_fits_leave_exactly_one(
    database: Database, metered: list[Charge]
) -> None:
    meter = SpendMeter(database)
    account, everyone = _limits()
    charges = _charges(metered, account, everyone, "account-a")

    results = await asyncio.gather(
        meter.create_reservation(charges, Decimal("0.70"), hold=HOLD),
        meter.create_reservation(charges, Decimal("0.70"), hold=HOLD),
        return_exceptions=True,
    )

    refused = [r for r in results if isinstance(r, PlatformAiQuotaReachedError)]
    assert len(refused) == 1, results
    assert (await meter.get_state(charges[0])).reserved_usd == Decimal("0.70")


async def test_a_lapsed_reservation_frees_what_it_held(
    database: Database, metered: list[Charge]
) -> None:
    meter = SpendMeter(database)
    account, everyone = _limits()
    charges = _charges(metered, account, everyone, "account-a")

    await meter.create_reservation(charges, Decimal("0.90"), hold=timedelta(microseconds=1))
    await asyncio.sleep(0.01)

    # Its process died without releasing it; the next one fits anyway.
    await meter.create_reservation(charges, Decimal("0.90"), hold=HOLD)


async def test_one_accounts_spend_counts_against_everyone_s_day(
    database: Database, metered: list[Charge]
) -> None:
    meter = SpendMeter(database)
    account, everyone = _limits()
    first = _charges(metered, account, everyone, "account-a")
    second = _charges(metered, account, everyone, "account-b")

    held = await meter.create_reservation(first, Decimal("0.90"), hold=HOLD)
    await meter.update_spent(held, Decimal("0.90"))
    await meter.delete_reservation(held)

    # account-b has its whole month, but the day has only $0.60 left.
    with pytest.raises(PlatformAiUnavailableError, match="Today is used"):
        await meter.create_reservation(second, Decimal("0.80"), hold=HOLD)
    await meter.create_reservation(second, Decimal("0.50"), hold=HOLD)
