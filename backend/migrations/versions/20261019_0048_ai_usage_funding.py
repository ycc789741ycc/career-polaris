"""The ledger says whose key paid for each call (ADR 0064).

``identity.ai_usage_ledger`` gains ``funding``: ``own``, the user's key, or
``platform``, the operator's. Every row already stored ran on the user's own
key, which the default records. A user's monthly cap sums only ``own`` rows.

Idempotent, since the baseline migration builds tables from the live ORM
metadata. Downgrading drops the column.
"""

from __future__ import annotations

from alembic import op

revision: str = "0048_ai_usage_funding"
down_revision: str | None = "0047_ai_usage_estimates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE identity.ai_usage_ledger"
        " ADD COLUMN IF NOT EXISTS funding varchar(16) NOT NULL DEFAULT 'own'"
    )
    op.execute(
        "DO $$ BEGIN"
        " ALTER TABLE identity.ai_usage_ledger ADD CONSTRAINT ck_ai_usage_ledger_funding"
        " CHECK (funding IN ('own', 'platform'));"
        " EXCEPTION WHEN duplicate_object THEN NULL; END $$"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE identity.ai_usage_ledger"
        " DROP CONSTRAINT IF EXISTS ck_ai_usage_ledger_funding,"
        " DROP COLUMN IF EXISTS funding"
    )
