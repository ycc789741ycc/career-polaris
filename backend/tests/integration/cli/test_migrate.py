"""Two places migrating at once take turns (ADR 0051).

The edge and the compute side both run `make migrate` when they start. The
lock is what keeps them from applying the same revision twice; the second
waits, then finds nothing pending.
"""

from __future__ import annotations

import os

import psycopg
import pytest

from cli.migrate import MIGRATION_LOCK_KEY, migration_lock
from kernel.db import get_psycopg_dsn

pytestmark = pytest.mark.integration


@pytest.fixture
def migrator_dsn() -> str:
    url = os.environ.get("MIGRATOR_DATABASE_URL")
    if not url:
        pytest.fail("MIGRATOR_DATABASE_URL is missing; run through `make test-integration`.")
    return get_psycopg_dsn(url)


def _try_lock(dsn: str) -> bool:
    """Whether another session could take the lock right now."""
    with psycopg.connect(dsn, autocommit=True) as connection:
        row = connection.execute(
            "SELECT pg_try_advisory_lock(%s)", (MIGRATION_LOCK_KEY,)
        ).fetchone()
        taken = bool(row and row[0])
        if taken:
            connection.execute("SELECT pg_advisory_unlock(%s)", (MIGRATION_LOCK_KEY,))
        return taken


def test_a_second_place_cannot_migrate_while_the_first_does(migrator_dsn: str) -> None:
    with migration_lock(migrator_dsn):
        assert not _try_lock(migrator_dsn)


def test_the_lock_is_free_once_a_migration_ends(migrator_dsn: str) -> None:
    with migration_lock(migrator_dsn):
        pass
    assert _try_lock(migrator_dsn)


def test_the_lock_is_free_after_a_migration_fails(migrator_dsn: str) -> None:
    with pytest.raises(RuntimeError), migration_lock(migrator_dsn):
        raise RuntimeError("a revision failed")
    assert _try_lock(migrator_dsn)
