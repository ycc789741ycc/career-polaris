"""Heartbeats, against the real database and roles (ADR 0052).

The worker beats as app_rw and the crawler as crawler_rw, which has no grant
on any user schema but may keep its own row here. Each test reads only the row
it wrote: a worker running against the same database beats too.
"""

from __future__ import annotations

import time
import uuid

import psycopg
import pytest

from kernel.config import Settings, Unit
from kernel.db import Database, get_psycopg_dsn
from kernel.presence import Heartbeat, get_presence

pytestmark = pytest.mark.integration


def _row(dsn: str, process_id: uuid.UUID) -> tuple[str, object, object] | None:
    with psycopg.connect(dsn) as connection:
        found = connection.execute(
            "SELECT unit, started_at, seen_at FROM presence.process WHERE id = %s",
            (process_id,),
        ).fetchone()
    return None if found is None else (str(found[0]), found[1], found[2])


def _wait_for_row(dsn: str, process_id: uuid.UUID) -> tuple[str, object, object]:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        found = _row(dsn, process_id)
        if found is not None:
            return found
        time.sleep(0.05)
    pytest.fail("the heartbeat never wrote its row")


def test_a_worker_beats_and_removes_its_row_when_it_stops(settings: Settings) -> None:
    dsn = get_psycopg_dsn(settings.require_database_url())
    heartbeat = Heartbeat(dsn, Unit.WORKER, interval_seconds=0.1)
    heartbeat.start()
    try:
        unit, started_at, seen_at = _wait_for_row(dsn, heartbeat.process_id)
        assert unit == "worker"
        assert started_at is not None and seen_at is not None
    finally:
        heartbeat.stop()

    assert _row(dsn, heartbeat.process_id) is None


def test_the_crawler_role_keeps_its_own_heartbeat(settings: Settings) -> None:
    crawler_dsn = get_psycopg_dsn(settings.require_crawler_database_url())
    heartbeat = Heartbeat(crawler_dsn, Unit.CRAWLER, interval_seconds=0.1)
    heartbeat.start()
    try:
        assert _wait_for_row(crawler_dsn, heartbeat.process_id)[0] == "crawler"
    finally:
        heartbeat.stop()


async def test_a_beating_worker_reads_as_online(settings: Settings, database: Database) -> None:
    heartbeat = Heartbeat(
        get_psycopg_dsn(settings.require_database_url()), Unit.WORKER, interval_seconds=0.1
    )
    heartbeat.start()
    try:
        _wait_for_row(get_psycopg_dsn(settings.require_database_url()), heartbeat.process_id)
        presence = await get_presence(database, away_after_seconds=30)
    finally:
        heartbeat.stop()

    assert presence.worker.is_online
    assert presence.worker.seen_at is not None
