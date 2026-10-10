"""The ledger keeps each call's estimate beside what it really used.

``identity.ai_usage_ledger`` gains ``estimated_input_tokens`` and
``estimated_cost_usd``, what the call was priced at before it was made, and
``is_estimated``, true when the counts are ours rather than the provider's (a
stream that reported none, or one cut short). Rows already stored cannot say
which of them were streamed, and so counted from characters; they keep no
estimate, and a report tells them apart by that.

Idempotent, since the baseline migration builds tables from the live ORM
metadata. Downgrading drops the columns.
"""

from __future__ import annotations

from alembic import op

revision: str = "0047_ai_usage_estimates"
down_revision: str | None = "0046_atlassian_account_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE identity.ai_usage_ledger"
        " ADD COLUMN IF NOT EXISTS estimated_input_tokens integer,"
        " ADD COLUMN IF NOT EXISTS estimated_cost_usd numeric(12, 6),"
        " ADD COLUMN IF NOT EXISTS is_estimated boolean NOT NULL DEFAULT false"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE identity.ai_usage_ledger"
        " DROP COLUMN IF EXISTS estimated_input_tokens,"
        " DROP COLUMN IF EXISTS estimated_cost_usd,"
        " DROP COLUMN IF EXISTS is_estimated"
    )
