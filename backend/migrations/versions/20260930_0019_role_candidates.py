"""Candidate roles from the strength assessment (ADR 0024).

* ``rolemap.role_candidate``: owner zone, under RLS. The roles the latest
  analysis recommended from the user's strengths, in its order, each placed on
  the role it became or left unplaced when the market lacks it. Each analysis
  replaces the set.

Written to be idempotent: the baseline migration builds tables from the live
ORM metadata, so on a fresh database the table already exists, with its
policy.

Nothing is backfilled. Roles built from clusters stay on the map until the
first build after the next analysis reconciles them against the candidates.

Downgrading drops the table and the candidates in it.
"""

from __future__ import annotations

from alembic import op

revision: str = "0019_role_candidates"
down_revision: str | None = "0018_organic_and_plain_templates"
branch_labels = None
depends_on = None

_APP_USER = "app.user_id"
_TABLE = "rolemap.role_candidate"


def upgrade() -> None:
    op.execute(
        f"CREATE TABLE IF NOT EXISTS {_TABLE} ("
        " id uuid NOT NULL,"
        " owner_id uuid NOT NULL,"
        " assessment_id uuid NOT NULL,"
        " rank integer NOT NULL,"
        " title varchar(255) NOT NULL,"
        " description text NOT NULL,"
        " dimension_keys jsonb NOT NULL,"
        " role_id uuid,"
        " opening_count integer NOT NULL DEFAULT 0,"
        " created_at timestamptz NOT NULL DEFAULT now(),"
        " CONSTRAINT pk_role_candidate PRIMARY KEY (id),"
        " CONSTRAINT uq_role_candidate_owner_id UNIQUE (owner_id, rank),"
        " CONSTRAINT fk_role_candidate_role_id_role FOREIGN KEY (role_id)"
        " REFERENCES rolemap.role (id) ON DELETE SET NULL"
        ")"
    )
    op.execute(f"CREATE INDEX IF NOT EXISTS ix_role_candidate_owner_id ON {_TABLE} (owner_id)")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {_TABLE} TO app_rw")
    op.execute(f"ALTER TABLE {_TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {_TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS owner_isolation ON {_TABLE}")
    op.execute(
        f"CREATE POLICY owner_isolation ON {_TABLE} FOR ALL "
        f"USING (owner_id::text = current_setting('{_APP_USER}', true)) "
        f"WITH CHECK (owner_id::text = current_setting('{_APP_USER}', true))"
    )


def downgrade() -> None:
    op.execute(f"DROP TABLE IF EXISTS {_TABLE}")
