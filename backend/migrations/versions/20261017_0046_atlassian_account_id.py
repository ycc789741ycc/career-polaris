"""A Jira connection keeps the Atlassian accountId it was made with (ADR 0061).

``profile.source_connection`` gains ``external_account_id``, nullable: the
personal data report names each account we hold data about by it, and GitHub
connections keep none. Rows already stored get it on their next sync.

Idempotent, since the baseline migration builds tables from the live ORM
metadata. Downgrading drops the column.
"""

from __future__ import annotations

from alembic import op

revision: str = "0046_atlassian_account_id"
down_revision: str | None = "0045_account_limits"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE profile.source_connection"
        " ADD COLUMN IF NOT EXISTS external_account_id varchar(128)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE profile.source_connection DROP COLUMN IF EXISTS external_account_id")
