"""Role subscriptions and manual re-crawls are gone (domain decision 22, ADR 0019).

A watched role was a second way to aim the Advisor, beside the role map's
selection. With it go:

* ``market_user.company_subscription``, with its ``fanout_read`` policy. The
  one on ``market_user.market_preference`` stays: the fan-out still resolves a
  market change to the users whose target locations take it in.
* ``market_user.manual_refresh_log``, which only capped re-crawls of a watched
  company.
* the ``subscription`` kind of Target: ``subscription_id`` on ``gapplan.plan``
  and ``resume.resume``, and the value in their ``target_kind`` checks.

Plans and résumés aimed at a subscription are deleted first — their milestones,
tasks, versions, revisions and exports go with them by cascade — and the
migration says how many.

Written to be idempotent: the baseline migration builds tables from the live
ORM metadata, so on a fresh database none of this exists.

Downgrading restores the tables, the column and the checks, empty: the deleted
rows do not come back.
"""

from __future__ import annotations

import logging

from alembic import op
from sqlalchemy import text

revision: str = "0013_drop_role_subscriptions"
down_revision: str | None = "0012_drop_evidence_confidence"
branch_labels = None
depends_on = None

log = logging.getLogger("alembic.runtime.migration")

# (table, constraint prefix) for each consumer that stores a Target.
_TARGET_TABLES = (("gapplan.plan", "ck_plan"), ("resume.resume", "ck_resume"))


def upgrade() -> None:
    bind = op.get_bind()
    for table, prefix in _TARGET_TABLES:
        # A fresh database's tables come from today's metadata, which has had
        # no ``target_kind`` since ADR 0022: there is nothing to delete or
        # re-check, and the checks below would name columns it lacks.
        if not _has_column(table, "target_kind"):
            continue
        # The migrator owns the table, but FORCE ROW LEVEL SECURITY holds even
        # the owner to the per-user policy, which would match no row here. Lift
        # it for the one statement. The table names are this module's constants.
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        deleted = bind.execute(
            text(f"DELETE FROM {table} WHERE target_kind = 'subscription'")  # noqa: S608
        ).rowcount
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        log.info("Deleted %s row(s) of %s aimed at a subscription", deleted, table)
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {prefix}_one_target")
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {prefix}_target_kind")
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS subscription_id")
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT {prefix}_one_target "
            "CHECK (num_nonnulls(job_posting_id, private_posting_id) = 1)"
        )
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT {prefix}_target_kind "
            "CHECK (target_kind IN ('matchedPosting', 'privatePosting'))"
        )

    op.execute("DROP TABLE IF EXISTS market_user.manual_refresh_log")
    # Dropping the table drops its policies, fanout_read among them.
    op.execute("DROP TABLE IF EXISTS market_user.company_subscription")


def _has_column(table: str, column: str) -> bool:
    schema, name = table.split(".")
    return (
        op.get_bind()
        .execute(
            text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_schema = :schema AND table_name = :name AND column_name = :column"
            ),
            {"schema": schema, "name": name, "column": column},
        )
        .first()
        is not None
    )


def downgrade() -> None:
    op.execute(
        "CREATE TABLE IF NOT EXISTS market_user.company_subscription ("
        " id uuid NOT NULL,"
        " owner_id uuid NOT NULL,"
        " company_id uuid NOT NULL,"
        " company_name varchar(255) NOT NULL,"
        " role_title varchar(255) NOT NULL DEFAULT '',"
        " role_id uuid,"
        " url varchar(1024),"
        " coverage varchar(16) NOT NULL DEFAULT 'manual',"
        " last_refreshed_at timestamp with time zone,"
        " created_at timestamp with time zone NOT NULL DEFAULT now(),"
        " updated_at timestamp with time zone NOT NULL DEFAULT now(),"
        " CONSTRAINT pk_company_subscription PRIMARY KEY (id),"
        " CONSTRAINT uq_company_subscription_owner_id UNIQUE (owner_id, company_id, role_title)"
        ")"
    )
    op.execute(
        "CREATE TABLE IF NOT EXISTS market_user.manual_refresh_log ("
        " id uuid NOT NULL,"
        " owner_id uuid NOT NULL,"
        " company_id uuid NOT NULL,"
        " requested_at timestamp with time zone NOT NULL DEFAULT now(),"
        " CONSTRAINT pk_manual_refresh_log PRIMARY KEY (id)"
        ")"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_manual_refresh_log_owner_day "
        "ON market_user.manual_refresh_log (owner_id, requested_at)"
    )
    for table in ("market_user.company_subscription", "market_user.manual_refresh_log"):
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO app_rw")
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS owner_isolation ON {table}")
        op.execute(
            f"CREATE POLICY owner_isolation ON {table} FOR ALL "
            "USING (owner_id::text = current_setting('app.user_id', true)) "
            "WITH CHECK (owner_id::text = current_setting('app.user_id', true))"
        )
    op.execute("DROP POLICY IF EXISTS fanout_read ON market_user.company_subscription")
    op.execute(
        "CREATE POLICY fanout_read ON market_user.company_subscription FOR SELECT "
        "USING (current_setting('app.fanout', true) = 'on')"
    )

    for table, prefix in _TARGET_TABLES:
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS subscription_id uuid")
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {prefix}_one_target")
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {prefix}_target_kind")
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT {prefix}_one_target "
            "CHECK (num_nonnulls(job_posting_id, subscription_id, private_posting_id) = 1)"
        )
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT {prefix}_target_kind "
            "CHECK (target_kind IN ('matchedPosting', 'subscription', 'privatePosting'))"
        )
