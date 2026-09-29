"""A role can be the user's own (domain decision 25, ADR 0021).

``rolemap.role`` gains ``origin`` (``recommended`` or ``custom``), a custom
role's optional ``company_name``, and its optional ``private_posting_id``: the
JD the user pasted with it, in ``market_user.private_job_posting``.

A JD already pasted is not a Target of its own any more; it belongs to a custom
role. Each one with no role yet becomes a custom role, titled from the JD, at
its company, and the migration says how many. The next build reads its
requirements from the JD.

Written to be idempotent: the baseline migration builds tables from the live
ORM metadata, so on a fresh database the columns already exist.

Downgrading deletes custom roles (their fits and members go with them where
they cascade) and drops the columns. The JDs themselves stay.
"""

from __future__ import annotations

import logging

from alembic import op
from sqlalchemy import text

revision: str = "0015_custom_roles"
down_revision: str | None = "0014_drop_role_map_setting"
branch_labels = None
depends_on = None

log = logging.getLogger("alembic.runtime.migration")

# Both tables are under FORCE ROW LEVEL SECURITY, which holds even their owner,
# the migrator, to the per-user policy. The data step lifts it for its own
# statements only.
_FORCED = ("rolemap.role", "market_user.private_job_posting")


def upgrade() -> None:
    op.execute(
        "ALTER TABLE rolemap.role "
        "ADD COLUMN IF NOT EXISTS origin varchar(16) NOT NULL DEFAULT 'recommended'"
    )
    op.execute("ALTER TABLE rolemap.role ADD COLUMN IF NOT EXISTS company_name varchar(255)")
    op.execute("ALTER TABLE rolemap.role ADD COLUMN IF NOT EXISTS private_posting_id uuid")
    op.execute("ALTER TABLE rolemap.role DROP CONSTRAINT IF EXISTS ck_role_origin")
    op.execute(
        "ALTER TABLE rolemap.role ADD CONSTRAINT ck_role_origin "
        "CHECK (origin IN ('recommended', 'custom'))"
    )

    for table in _FORCED:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    created = (
        op.get_bind()
        .execute(
            text(
                "INSERT INTO rolemap.role "
                "(id, owner_id, name, origin, company_name, private_posting_id) "
                "SELECT gen_random_uuid(), jd.owner_id, left(jd.title, 255), 'custom', "
                "       nullif(btrim(jd.company_name), ''), jd.id "
                "FROM market_user.private_job_posting jd "
                "WHERE NOT EXISTS ("
                "  SELECT 1 FROM rolemap.role r WHERE r.private_posting_id = jd.id"
                ")"
            )
        )
        .rowcount
    )
    for table in _FORCED:
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    log.info("Made %s pasted JD(s) into custom roles", created)


def downgrade() -> None:
    op.execute("ALTER TABLE rolemap.role NO FORCE ROW LEVEL SECURITY")
    op.execute("DELETE FROM rolemap.role WHERE origin = 'custom'")
    op.execute("ALTER TABLE rolemap.role FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE rolemap.role DROP CONSTRAINT IF EXISTS ck_role_origin")
    for column in ("private_posting_id", "company_name", "origin"):
        op.execute(f"ALTER TABLE rolemap.role DROP COLUMN IF EXISTS {column}")
