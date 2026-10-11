"""An opening is scored with AI when its gap analysis runs (ADR 0073).

Three tables in the ``target`` schema, owner zone, under RLS, with no grant to
the crawler, keyed on the shared posting's id:

* ``target.opening_requirement``: what the opening's description asks for,
  read once.
* ``target.opening_requirement_fit``: the AI's mapping of those requirements
  onto the user's dimensions.
* ``target.opening_fit``: the fit worked out from that, locally.

``rolemap.posting_fit``, the fits each build worked out for every opening from
its role's by embedding similarity (ADR 0032), is dropped: nothing reads them
any more, and they are never shown. Nothing is moved across: a derived fit is
not an AI fit of the opening, so an opening is scored again by its next gap
analysis.

Idempotent: the baseline builds tables from the live ORM metadata, so on a
fresh database the new tables already exist, and only the grants and the
policies are new. Downgrading drops the new tables and recreates
``rolemap.posting_fit`` empty; the next build fills it again.
"""

from __future__ import annotations

from alembic import op

revision: str = "0056_opening_fit_in_target"
down_revision: str | None = "0055_cancelled_runs"
branch_labels = None
depends_on = None

_APP_USER = "app.user_id"
_REQUIREMENT = "target.opening_requirement"
_REQUIREMENT_FIT = "target.opening_requirement_fit"
_FIT = "target.opening_fit"
_OLD_FIT = "rolemap.posting_fit"


def upgrade() -> None:
    op.execute(
        f"CREATE TABLE IF NOT EXISTS {_REQUIREMENT} ("
        " id uuid NOT NULL,"
        " owner_id uuid NOT NULL,"
        " job_posting_id uuid NOT NULL,"
        " statement text NOT NULL,"
        " weight double precision NOT NULL,"
        " expected_level varchar(32) NOT NULL,"
        " CONSTRAINT pk_opening_requirement PRIMARY KEY (id)"
        ")"
    )
    op.execute(
        f"CREATE INDEX IF NOT EXISTS ix_opening_requirement_owner_id ON {_REQUIREMENT} (owner_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_opening_requirement_owner_posting"
        f" ON {_REQUIREMENT} (owner_id, job_posting_id)"
    )
    op.execute(
        f"CREATE TABLE IF NOT EXISTS {_REQUIREMENT_FIT} ("
        " id uuid NOT NULL,"
        " owner_id uuid NOT NULL,"
        " job_posting_id uuid NOT NULL,"
        " assessment_id uuid NOT NULL,"
        " requirements jsonb NOT NULL,"
        " requirement_map jsonb NOT NULL,"
        " target_profile jsonb NOT NULL,"
        " reasoning text NOT NULL,"
        " model_id varchar(128) NOT NULL,"
        " template_version varchar(128) NOT NULL,"
        " requirements_digest varchar(64) NOT NULL,"
        " created_at timestamptz NOT NULL DEFAULT now(),"
        " CONSTRAINT pk_opening_requirement_fit PRIMARY KEY (id)"
        ")"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_opening_requirement_fit_owner_id"
        f" ON {_REQUIREMENT_FIT} (owner_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_opening_requirement_fit_owner_posting"
        f" ON {_REQUIREMENT_FIT} (owner_id, job_posting_id, created_at)"
    )
    op.execute(
        f"CREATE TABLE IF NOT EXISTS {_FIT} ("
        " id uuid NOT NULL,"
        " owner_id uuid NOT NULL,"
        " job_posting_id uuid NOT NULL,"
        " source_fit_id uuid NOT NULL,"
        " assessment_id uuid NOT NULL,"
        " score integer NOT NULL,"
        " requirements jsonb NOT NULL,"
        " requirement_map jsonb NOT NULL,"
        " target_profile jsonb NOT NULL,"
        " gaps jsonb NOT NULL,"
        " uncovered jsonb NOT NULL,"
        " created_at timestamptz NOT NULL DEFAULT now(),"
        " CONSTRAINT pk_opening_fit PRIMARY KEY (id),"
        " CONSTRAINT fk_opening_fit_source_fit_id_opening_requirement_fit"
        f" FOREIGN KEY (source_fit_id) REFERENCES {_REQUIREMENT_FIT} (id) ON DELETE CASCADE"
        ")"
    )
    op.execute(f"CREATE INDEX IF NOT EXISTS ix_opening_fit_owner_id ON {_FIT} (owner_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_opening_fit_owner_posting"
        f" ON {_FIT} (owner_id, job_posting_id, created_at)"
    )
    for table in (_REQUIREMENT, _REQUIREMENT_FIT, _FIT):
        _owner_isolation(table)
    op.execute(f"DROP TABLE IF EXISTS {_OLD_FIT}")


def downgrade() -> None:
    for table in (_FIT, _REQUIREMENT_FIT, _REQUIREMENT):
        op.execute(f"DROP TABLE IF EXISTS {table}")
    op.execute(
        f"CREATE TABLE IF NOT EXISTS {_OLD_FIT} ("
        " id uuid NOT NULL,"
        " owner_id uuid NOT NULL,"
        " posting_key varchar(128) NOT NULL,"
        " source_fit_id uuid NOT NULL,"
        " role_id uuid NOT NULL,"
        " assessment_id uuid NOT NULL,"
        " score integer NOT NULL,"
        " requirements jsonb NOT NULL,"
        " requirement_map jsonb NOT NULL,"
        " target_profile jsonb NOT NULL,"
        " gaps jsonb NOT NULL,"
        " uncovered jsonb NOT NULL,"
        " created_at timestamptz NOT NULL DEFAULT now(),"
        " CONSTRAINT pk_posting_fit PRIMARY KEY (id),"
        " CONSTRAINT fk_posting_fit_role_id_role"
        " FOREIGN KEY (role_id) REFERENCES rolemap.role (id) ON DELETE CASCADE"
        ")"
    )
    op.execute(f"CREATE INDEX IF NOT EXISTS ix_posting_fit_owner_id ON {_OLD_FIT} (owner_id)")
    op.execute(
        f"CREATE INDEX IF NOT EXISTS ix_posting_fit_owner_role ON {_OLD_FIT} (owner_id, role_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_posting_fit_owner_key"
        f" ON {_OLD_FIT} (owner_id, posting_key, created_at)"
    )
    _owner_isolation(_OLD_FIT)


def _owner_isolation(table: str) -> None:
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO app_rw")
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS owner_isolation ON {table}")
    op.execute(
        f"CREATE POLICY owner_isolation ON {table} FOR ALL "
        f"USING (owner_id::text = current_setting('{_APP_USER}', true)) "
        f"WITH CHECK (owner_id::text = current_setting('{_APP_USER}', true))"
    )
