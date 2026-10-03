"""A gap plan and a tailored résumé record what they were drafted from (ADR 0035).

``gapplan.plan`` and ``resume.resume`` each gain:

* ``profile_version``: the version of the user's profile the draft read;
* ``target_digest``: a hash of the Target as the draft read it.

Both nullable. Rows already stored keep none, and read as neither outdated nor
current: their basis is unknown. Idempotent, since the baseline migration
builds tables from the live ORM metadata. Downgrading drops the columns.
"""

from __future__ import annotations

from alembic import op

revision: str = "0033_draft_basis"
down_revision: str | None = "0032_own_role_on_request"
branch_labels = None
depends_on = None

_TABLES = ("gapplan.plan", "resume.resume")


def upgrade() -> None:
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS profile_version integer")
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS target_digest varchar(64)")


def downgrade() -> None:
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS target_digest")
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS profile_version")
