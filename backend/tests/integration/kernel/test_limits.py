"""The limiter against the real database (ADR 0054). Each test limits a
subject of its own, so runs never count against one another."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import AsyncIterator
from datetime import timedelta

import pytest
import pytest_asyncio
from sqlalchemy import text

from kernel.db import Database
from kernel.errors import RateLimitedError
from kernel.limits import Limit, Limiter

pytestmark = pytest.mark.integration

THREE_A_DAY = Limit("test-uploads", 3, timedelta(days=1), "Enough for today.")


def _digest(limit: Limit, subject: str) -> str:
    return hashlib.sha256(f"{limit.name}\x00{subject}".encode()).hexdigest()


@pytest_asyncio.fixture
async def counted(database: Database) -> AsyncIterator[list[str]]:
    """Digests a test counted under; deleted afterwards, so it re-runs clean."""
    digests: list[str] = []
    yield digests
    async with database.shared() as session:
        await session.execute(
            text("DELETE FROM limits.counter WHERE key_digest = ANY(:digests)"),
            {"digests": digests},
        )


async def test_attempts_within_the_limit_pass_and_the_next_is_refused(
    database: Database, counted: list[str]
) -> None:
    limiter = Limiter(database)
    subject = f"account:{uuid.uuid4()}"
    counted.append(_digest(THREE_A_DAY, subject))

    for _ in range(3):
        await limiter.record_attempt(THREE_A_DAY, subject)
    with pytest.raises(RateLimitedError) as refused:
        await limiter.record_attempt(THREE_A_DAY, subject)

    assert refused.value.message.startswith("Enough for today. Try again in ")
    wait = refused.value.context["retry_after_seconds"]
    assert 0 < wait <= 24 * 3600


async def test_one_subject_past_its_limit_holds_nobody_else_up(
    database: Database, counted: list[str]
) -> None:
    limiter = Limiter(database)
    busy, other = f"account:{uuid.uuid4()}", f"account:{uuid.uuid4()}"
    counted.extend([_digest(THREE_A_DAY, busy), _digest(THREE_A_DAY, other)])
    for _ in range(3):
        await limiter.record_attempt(THREE_A_DAY, busy)

    await limiter.record_attempt(THREE_A_DAY, other)


async def test_the_next_window_starts_the_count_again(
    database: Database, counted: list[str]
) -> None:
    """A minute's window, with this window's counter moved into the past."""
    per_minute = Limit("test-syncs", 1, timedelta(minutes=1), "Wait.")
    limiter = Limiter(database)
    subject = f"account:{uuid.uuid4()}"
    counted.append(_digest(per_minute, subject))
    await limiter.record_attempt(per_minute, subject)
    async with database.shared() as session:
        await session.execute(
            text(
                "UPDATE limits.counter SET window_start = window_start - interval '1 minute' "
                "WHERE key_digest = :digest"
            ),
            {"digest": _digest(per_minute, subject)},
        )

    await limiter.record_attempt(per_minute, subject)


async def test_no_address_is_stored_only_its_digest(database: Database, counted: list[str]) -> None:
    limiter = Limiter(database)
    address = f"203.0.113.{uuid.uuid4().int % 250}"
    counted.append(_digest(THREE_A_DAY, address))
    await limiter.record_attempt(THREE_A_DAY, address)

    async with database.shared() as session:
        found = await session.execute(
            text("SELECT count(*) FROM limits.counter WHERE key_digest LIKE :like"),
            {"like": f"%{address}%"},
        )
    assert found.scalar_one() == 0
