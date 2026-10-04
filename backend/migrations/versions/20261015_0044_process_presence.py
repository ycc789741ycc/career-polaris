"""Heartbeats of the worker and the crawler (ADR 0052).

``presence.process`` holds a row per running worker or crawler process,
refreshed every few seconds, so the api can tell work waiting for an absent
machine from work that was lost.

The crawler writes its own row, so ``crawler_rw`` gets this one table beside
the shared market zone and the outbox: it holds a process id and two times,
and nothing about any user.

Idempotent: the baseline builds tables from the live ORM metadata, so on a
fresh database the table already exists, without these grants.
"""

from __future__ import annotations

from alembic import op

revision: str = "0044_process_presence"
down_revision: str | None = "0043_more_resume_fonts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute('CREATE SCHEMA IF NOT EXISTS "presence"')
    op.execute(
        "CREATE TABLE IF NOT EXISTS presence.process ("
        " id uuid NOT NULL,"
        " unit varchar(16) NOT NULL,"
        " started_at timestamptz NOT NULL,"
        " seen_at timestamptz NOT NULL,"
        " CONSTRAINT pk_process PRIMARY KEY (id))"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_process_unit_seen_at ON presence.process (unit, seen_at)"
    )
    op.execute('GRANT USAGE ON SCHEMA "presence" TO app_rw, crawler_rw')
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON presence.process TO app_rw, crawler_rw")


def downgrade() -> None:
    op.execute('DROP SCHEMA IF EXISTS "presence" CASCADE')
