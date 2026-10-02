"""A fit for every opening (Phase 8, ADR 0032).

Owner zone, under RLS: ``rolemap.posting_fit`` holds an opening's fit, worked
out locally from its role's (``basis = 'role'``), beside a posting of the
user's own's (``basis = 'own'``).

* ``role_id`` names an opening's role, and goes with it; a posting of the
  user's own has none. A check constraint ties the two.
* The basis check takes ``role``.

Nothing is written here: the next build works every opening's fit out, at no
cost, and until then an opening ranks by its role's fit, as before.

Idempotent, since the baseline migration builds tables from the live ORM
metadata. Downgrading deletes the openings' fits and drops the column.
"""

from __future__ import annotations

from alembic import op

revision: str = "0028_opening_fits"
down_revision: str | None = "0027_fit_requirements_digest"
branch_labels = None
depends_on = None

_TABLE = "rolemap.posting_fit"


def upgrade() -> None:
    op.execute(
        f"ALTER TABLE {_TABLE} ADD COLUMN IF NOT EXISTS role_id uuid"
        " CONSTRAINT fk_posting_fit_role_id_role REFERENCES rolemap.role (id) ON DELETE CASCADE"
    )
    op.execute(
        f"CREATE INDEX IF NOT EXISTS ix_posting_fit_owner_role ON {_TABLE} (owner_id, role_id)"
    )
    op.execute(f"ALTER TABLE {_TABLE} DROP CONSTRAINT IF EXISTS ck_posting_fit_basis")
    op.execute(
        f"ALTER TABLE {_TABLE} ADD CONSTRAINT ck_posting_fit_basis CHECK (basis IN ('own', 'role'))"
    )
    op.execute(f"ALTER TABLE {_TABLE} DROP CONSTRAINT IF EXISTS ck_posting_fit_role")
    op.execute(
        f"ALTER TABLE {_TABLE} ADD CONSTRAINT ck_posting_fit_role"
        " CHECK ((basis = 'role') = (role_id IS NOT NULL))"
    )


def downgrade() -> None:
    op.execute(f"ALTER TABLE {_TABLE} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"DELETE FROM {_TABLE} WHERE basis = 'role'")  # noqa: S608
    op.execute(f"ALTER TABLE {_TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {_TABLE} DROP CONSTRAINT IF EXISTS ck_posting_fit_role")
    op.execute(f"ALTER TABLE {_TABLE} DROP CONSTRAINT IF EXISTS ck_posting_fit_basis")
    op.execute(f"ALTER TABLE {_TABLE} ADD CONSTRAINT ck_posting_fit_basis CHECK (basis IN ('own'))")
    op.execute("DROP INDEX IF EXISTS rolemap.ix_posting_fit_owner_role")
    op.execute(f"ALTER TABLE {_TABLE} DROP COLUMN IF EXISTS role_id")
