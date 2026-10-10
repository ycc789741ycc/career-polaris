"""What the platform's AI key spends, per account and in all, reserved first
(ADR 0064).

``limits.spend_window`` keeps, per subject digest and window (a UTC day or a
calendar month), what was spent. ``limits.spend_reservation`` keeps what calls
in progress hold against it, until they are released or lapse at
``expires_at``. The api and the worker write both as ``app_rw``.

Idempotent: the baseline builds tables from the live ORM metadata, so on a
fresh database the tables already exist, and only the grants are new.
"""

from __future__ import annotations

from alembic import op

revision: str = "0049_platform_ai_spend"
down_revision: str | None = "0048_ai_usage_funding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute('CREATE SCHEMA IF NOT EXISTS "limits"')
    op.execute(
        "CREATE TABLE IF NOT EXISTS limits.spend_window ("
        " key_digest varchar(64) NOT NULL,"
        " window_start timestamptz NOT NULL,"
        " spent_usd numeric(12, 6) NOT NULL,"
        " CONSTRAINT pk_spend_window PRIMARY KEY (key_digest, window_start))"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_spend_window_window_start"
        " ON limits.spend_window (window_start)"
    )
    op.execute(
        "CREATE TABLE IF NOT EXISTS limits.spend_reservation ("
        " id uuid NOT NULL,"
        " key_digest varchar(64) NOT NULL,"
        " window_start timestamptz NOT NULL,"
        " amount_usd numeric(12, 6) NOT NULL,"
        " expires_at timestamptz NOT NULL,"
        " CONSTRAINT pk_spend_reservation PRIMARY KEY (id, key_digest))"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_spend_reservation_key_window"
        " ON limits.spend_reservation (key_digest, window_start)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_spend_reservation_expires_at"
        " ON limits.spend_reservation (expires_at)"
    )
    op.execute('GRANT USAGE ON SCHEMA "limits" TO app_rw')
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON limits.spend_window, limits.spend_reservation"
        " TO app_rw"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS limits.spend_reservation")
    op.execute("DROP TABLE IF EXISTS limits.spend_window")
