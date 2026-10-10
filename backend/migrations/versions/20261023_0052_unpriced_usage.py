"""The ledger says whether a call's model had a published rate.

``identity.ai_usage_ledger`` gains ``is_rate_published``. When it is false,
``cost_usd`` is the deliberately high fallback rather than what the provider
billed, and the user's monthly cap does not count the row: a guess must not
pause someone's work. Rows already stored are taken as priced, which is how
the cap counted them until now.

Idempotent, since the baseline migration builds tables from the live ORM
metadata. Downgrading drops the column.
"""

from __future__ import annotations

from alembic import op

revision: str = "0052_unpriced_usage"
down_revision: str | None = "0051_no_local_model"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE identity.ai_usage_ledger"
        " ADD COLUMN IF NOT EXISTS is_rate_published boolean NOT NULL DEFAULT true"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE identity.ai_usage_ledger DROP COLUMN IF EXISTS is_rate_published")
