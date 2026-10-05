"""Counters for the limits only the app can see (ADR 0054).

``limits.counter`` keeps, per limit and subject (an account, or a sign-up's
address), how many attempts fell in the current window. The subject is
stored only as a digest. The api writes it as ``app_rw``; nothing else
touches it.

Idempotent: the baseline builds tables from the live ORM metadata, so on a
fresh database the table already exists, without this grant.
"""

from __future__ import annotations

from alembic import op

revision: str = "0045_account_limits"
down_revision: str | None = "0044_process_presence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute('CREATE SCHEMA IF NOT EXISTS "limits"')
    op.execute(
        "CREATE TABLE IF NOT EXISTS limits.counter ("
        " key_digest varchar(64) NOT NULL,"
        " window_start timestamptz NOT NULL,"
        " hits integer NOT NULL,"
        " CONSTRAINT pk_counter PRIMARY KEY (key_digest, window_start))"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_counter_window_start ON limits.counter (window_start)"
    )
    op.execute('GRANT USAGE ON SCHEMA "limits" TO app_rw')
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON limits.counter TO app_rw")


def downgrade() -> None:
    op.execute('DROP SCHEMA IF EXISTS "limits" CASCADE')
