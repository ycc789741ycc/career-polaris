"""Background work records whether it is running (ADR 0006, ADR 0018).

* ``profile.source_connection.sync_started_at``: set while a sync is queued or
  running, cleared when it ends either way.
* ``assessment.analysis_run``: owner zone, under RLS. One row per requested
  analysis, created before the job runs.
* ``rolemap.build_run``: owner zone, under RLS. One row per requested role-map
  build, created before the job runs, and ``waiting`` when it was asked for
  during an analysis.

Written to be idempotent: the baseline migration builds tables from the live
ORM metadata, so on a fresh database these already exist, with their policy,
by the time this revision runs.
"""

from __future__ import annotations

from alembic import op

revision: str = "0011_run_status"
down_revision: str | None = "0010_evidence_tallies"
branch_labels = None
depends_on = None

_APP_USER = "app.user_id"
_ANALYSIS_RUN = "assessment.analysis_run"
_BUILD_RUN = "rolemap.build_run"


def upgrade() -> None:
    op.execute(
        "ALTER TABLE profile.source_connection ADD COLUMN IF NOT EXISTS sync_started_at timestamptz"
    )

    op.execute(
        f"CREATE TABLE IF NOT EXISTS {_ANALYSIS_RUN} ("
        " id uuid NOT NULL,"
        " owner_id uuid NOT NULL,"
        " status varchar(16) NOT NULL,"
        " error_code varchar(64),"
        " error_message text,"
        " started_at timestamptz NOT NULL DEFAULT now(),"
        " finished_at timestamptz,"
        " CONSTRAINT pk_analysis_run PRIMARY KEY (id),"
        " CONSTRAINT ck_analysis_run_status CHECK (status IN ('running', 'ready', 'failed'))"
        ")"
    )
    op.execute(f"CREATE INDEX IF NOT EXISTS ix_analysis_run_owner_id ON {_ANALYSIS_RUN} (owner_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_analysis_run_owner_started "
        f"ON {_ANALYSIS_RUN} (owner_id, started_at)"
    )

    op.execute(
        f"CREATE TABLE IF NOT EXISTS {_BUILD_RUN} ("
        " id uuid NOT NULL,"
        " owner_id uuid NOT NULL,"
        " status varchar(16) NOT NULL,"
        " error_code varchar(64),"
        " error_message text,"
        " requested_at timestamptz NOT NULL DEFAULT now(),"
        " started_at timestamptz,"
        " finished_at timestamptz,"
        " CONSTRAINT pk_build_run PRIMARY KEY (id),"
        " CONSTRAINT ck_build_run_status"
        " CHECK (status IN ('waiting', 'running', 'ready', 'failed'))"
        ")"
    )
    op.execute(f"CREATE INDEX IF NOT EXISTS ix_build_run_owner_id ON {_BUILD_RUN} (owner_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_build_run_owner_requested "
        f"ON {_BUILD_RUN} (owner_id, requested_at)"
    )

    for table in (_ANALYSIS_RUN, _BUILD_RUN):
        _owner_zone(table)


def _owner_zone(table: str) -> None:
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO app_rw")
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS owner_isolation ON {table}")
    op.execute(
        f"CREATE POLICY owner_isolation ON {table} FOR ALL "
        f"USING (owner_id::text = current_setting('{_APP_USER}', true)) "
        f"WITH CHECK (owner_id::text = current_setting('{_APP_USER}', true))"
    )


def downgrade() -> None:
    op.execute(f"DROP TABLE IF EXISTS {_BUILD_RUN}")
    op.execute(f"DROP TABLE IF EXISTS {_ANALYSIS_RUN}")
    op.execute("ALTER TABLE profile.source_connection DROP COLUMN IF EXISTS sync_started_at")
