"""A posting of the user's own can be uploaded as a file (ADR 0033).

``target.private_job_posting`` gains:

* ``source``: ``pasted`` (every posting so far) or ``uploaded``;
* ``filename`` and ``content_type``: the uploaded file's;
* ``storage_key``: where the file waits in object storage until the worker has
  read it.

``job_description`` becomes nullable: an uploaded posting has none until its
file is read. A check keeps that the only way to have none.

Idempotent, since the baseline migration builds tables from the live ORM
metadata. Downgrading deletes the uploaded postings whose file was never read
(their files stay in object storage, under the owner's prefix, to be cleaned
up there) and drops the columns.
"""

from __future__ import annotations

from alembic import op

revision: str = "0031_upload_own_posting"
down_revision: str | None = "0030_own_posting_in_target"
branch_labels = None
depends_on = None

_TABLE = "target.private_job_posting"


def upgrade() -> None:
    op.execute(
        f"ALTER TABLE {_TABLE}"
        " ADD COLUMN IF NOT EXISTS source varchar(16) NOT NULL DEFAULT 'pasted'"
    )
    op.execute(f"ALTER TABLE {_TABLE} ADD COLUMN IF NOT EXISTS filename varchar(255)")
    op.execute(f"ALTER TABLE {_TABLE} ADD COLUMN IF NOT EXISTS content_type varchar(128)")
    op.execute(f"ALTER TABLE {_TABLE} ADD COLUMN IF NOT EXISTS storage_key varchar(512)")
    op.execute(f"ALTER TABLE {_TABLE} ALTER COLUMN job_description DROP NOT NULL")
    op.execute(f"ALTER TABLE {_TABLE} DROP CONSTRAINT IF EXISTS ck_private_job_posting_source")
    op.execute(
        f"ALTER TABLE {_TABLE} ADD CONSTRAINT ck_private_job_posting_source"
        " CHECK (source IN ('pasted', 'uploaded'))"
    )
    op.execute(
        f"ALTER TABLE {_TABLE} DROP CONSTRAINT IF EXISTS ck_private_job_posting_job_description"
    )
    op.execute(
        f"ALTER TABLE {_TABLE} ADD CONSTRAINT ck_private_job_posting_job_description"
        " CHECK (job_description IS NOT NULL"
        " OR (source = 'uploaded' AND storage_key IS NOT NULL))"
    )


def downgrade() -> None:
    op.execute(f"ALTER TABLE {_TABLE} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"DELETE FROM {_TABLE} WHERE job_description IS NULL")  # noqa: S608
    op.execute(f"ALTER TABLE {_TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"ALTER TABLE {_TABLE} DROP CONSTRAINT IF EXISTS ck_private_job_posting_job_description"
    )
    op.execute(f"ALTER TABLE {_TABLE} DROP CONSTRAINT IF EXISTS ck_private_job_posting_source")
    op.execute(f"ALTER TABLE {_TABLE} ALTER COLUMN job_description SET NOT NULL")
    for column in ("storage_key", "content_type", "filename", "source"):
        op.execute(f"ALTER TABLE {_TABLE} DROP COLUMN IF EXISTS {column}")
