"""A posting of the user's own is added without spending anything, and can be
filled in by hand (ADR 0034).

``target.private_job_posting`` gains:

* ``has_placeholder_title``: uploaded without a title, so named after its file
  until the file is read;
* ``has_estimated_requirements``: filled in with nothing listed, so what it
  asks for is estimated from its title.

``source`` may now be ``filled_in``, and such a posting with nothing listed is
the one other way to have no ``job_description``. Rows already stored are
untouched: both flags default to false.

Idempotent, since the baseline migration builds tables from the live ORM
metadata. Downgrading deletes the postings filled in by hand (a pasted JD's
check cannot hold them) and drops the columns.
"""

from __future__ import annotations

from alembic import op

revision: str = "0032_own_role_on_request"
down_revision: str | None = "0031_upload_own_posting"
branch_labels = None
depends_on = None

_TABLE = "target.private_job_posting"


def upgrade() -> None:
    op.execute(
        f"ALTER TABLE {_TABLE}"
        " ADD COLUMN IF NOT EXISTS has_placeholder_title boolean NOT NULL DEFAULT false"
    )
    op.execute(
        f"ALTER TABLE {_TABLE}"
        " ADD COLUMN IF NOT EXISTS has_estimated_requirements boolean NOT NULL DEFAULT false"
    )
    op.execute(f"ALTER TABLE {_TABLE} DROP CONSTRAINT IF EXISTS ck_private_job_posting_source")
    op.execute(
        f"ALTER TABLE {_TABLE} ADD CONSTRAINT ck_private_job_posting_source"
        " CHECK (source IN ('pasted', 'uploaded', 'filled_in'))"
    )
    op.execute(
        f"ALTER TABLE {_TABLE} DROP CONSTRAINT IF EXISTS ck_private_job_posting_job_description"
    )
    op.execute(
        f"ALTER TABLE {_TABLE} ADD CONSTRAINT ck_private_job_posting_job_description"
        " CHECK (job_description IS NOT NULL"
        " OR (source = 'uploaded' AND storage_key IS NOT NULL)"
        " OR (source = 'filled_in' AND has_estimated_requirements))"
    )


def downgrade() -> None:
    op.execute(f"ALTER TABLE {_TABLE} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"DELETE FROM {_TABLE} WHERE source = 'filled_in'")  # noqa: S608
    op.execute(f"ALTER TABLE {_TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"ALTER TABLE {_TABLE} DROP CONSTRAINT IF EXISTS ck_private_job_posting_job_description"
    )
    op.execute(
        f"ALTER TABLE {_TABLE} ADD CONSTRAINT ck_private_job_posting_job_description"
        " CHECK (job_description IS NOT NULL"
        " OR (source = 'uploaded' AND storage_key IS NOT NULL))"
    )
    op.execute(f"ALTER TABLE {_TABLE} DROP CONSTRAINT IF EXISTS ck_private_job_posting_source")
    op.execute(
        f"ALTER TABLE {_TABLE} ADD CONSTRAINT ck_private_job_posting_source"
        " CHECK (source IN ('pasted', 'uploaded'))"
    )
    for column in ("has_estimated_requirements", "has_placeholder_title"):
        op.execute(f"ALTER TABLE {_TABLE} DROP COLUMN IF EXISTS {column}")
