"""Runs every pending migration to completion, then exits.

The `migrate` compose service, which `make migrate` runs before any app
container starts — in either mode, and in every place the app runs. Alembic
brings the schema to head, then Procrastinate's job tables are applied, then
the baseline crawl list is loaded. Any failure raises and exits non-zero, so a
failed migration fails the start rather than letting the app serve on a
half-migrated database.

The edge and the compute side each migrate when they start (ADR 0051), so the
whole run holds a Postgres advisory lock: a place starting at the same moment
waits, then finds nothing pending. A place whose image is older than the schema
stops here, rather than running code against tables it does not know.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterable, Iterator
from contextlib import contextmanager

import psycopg
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text

from cli import apply_job_schema, seed_baseline
from kernel.db import get_psycopg_dsn

# The same constant in every place; it names this lock and nothing else.
MIGRATION_LOCK_KEY = 0x4A53_414D_4947

VERSION_TABLE = "migrations.alembic_version"


class SchemaAheadError(RuntimeError):
    """The database is at a revision this image's migrations do not contain."""


def main() -> None:
    url = _get_migrator_url()
    config = Config("alembic.ini")
    known = {script.revision for script in ScriptDirectory.from_config(config).walk_revisions()}
    with migration_lock(get_psycopg_dsn(url)):
        assert_schema_known(_get_applied_revisions(url), known)
        command.upgrade(config, "head")
        asyncio.run(apply_job_schema.main())
        asyncio.run(seed_baseline.main())


@contextmanager
def migration_lock(dsn: str) -> Iterator[None]:
    """Hold the migration lock for the block, waiting for it while it is taken.

    A session-level advisory lock on a connection of its own: Alembic and
    Procrastinate open their own connections, and the lock outlives their
    transactions. Closing the connection releases it, however the block ends.
    """
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute("SELECT pg_advisory_lock(%s)", (MIGRATION_LOCK_KEY,))
        try:
            yield
        finally:
            connection.execute("SELECT pg_advisory_unlock(%s)", (MIGRATION_LOCK_KEY,))


def assert_schema_known(applied: Iterable[str], known: set[str]) -> None:
    """Refuse a database that a newer release than this image has migrated."""
    unknown = sorted(revision for revision in applied if revision not in known)
    if unknown:
        raise SchemaAheadError(
            f"the database is at {', '.join(unknown)}, which this image does not know: "
            "a newer release migrated it. Run the release the edge runs here too."
        )


def _get_applied_revisions(url: str) -> list[str]:
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            found = connection.execute(text("SELECT to_regclass(:t)"), {"t": VERSION_TABLE})
            if found.scalar() is None:
                return []
            rows = connection.execute(text(f"SELECT version_num FROM {VERSION_TABLE}"))  # noqa: S608
            return [str(row[0]) for row in rows]
    finally:
        engine.dispose()


def _get_migrator_url() -> str:
    url = os.environ.get("MIGRATOR_DATABASE_URL")
    if not url:
        raise RuntimeError("MIGRATOR_DATABASE_URL is required to run migrations")
    return url


if __name__ == "__main__":
    main()
