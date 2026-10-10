"""Eligible accounts run on CareerPolaris AI by default (ADR 0066).

With no choice made, a Google-verified account now runs on the platform's key.
So that nobody who stored a key of their own is moved off it by this, every
account with a stored key and no choice is given an ``own`` choice. There is
no terms step any more, so ``identity.ai_source_choice`` loses
``platform_terms_accepted_at``.

FORCE ROW LEVEL SECURITY holds even the owning migrator to the per-user policy,
so it is lifted while every owner's rows are read and written, and restored
after (as migration 0030 does). Idempotent: an account given its choice once is
skipped. Downgrading only adds the column back, empty.
"""

from __future__ import annotations

from alembic import op

revision: str = "0053_platform_by_default"
down_revision: str | None = "0052_unpriced_usage"
branch_labels = None
depends_on = None

# Every account with a stored key and no choice keeps its own key. Written to
# hold under a per-user policy too, so a test can run it as one owner.
BACKFILL_OWN_CHOICES = (
    "INSERT INTO identity.ai_source_choice (id, owner_id, source)"
    " SELECT gen_random_uuid(), credential.owner_id, 'own'"
    " FROM identity.provider_credential AS credential"
    " WHERE NOT EXISTS (SELECT 1 FROM identity.ai_source_choice AS choice"
    "  WHERE choice.owner_id = credential.owner_id)"
)


def upgrade() -> None:
    op.execute("ALTER TABLE identity.provider_credential NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE identity.ai_source_choice NO FORCE ROW LEVEL SECURITY")
    op.execute(BACKFILL_OWN_CHOICES)
    op.execute("ALTER TABLE identity.ai_source_choice FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE identity.provider_credential FORCE ROW LEVEL SECURITY")
    op.execute(
        "ALTER TABLE identity.ai_source_choice DROP COLUMN IF EXISTS platform_terms_accepted_at"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE identity.ai_source_choice"
        " ADD COLUMN IF NOT EXISTS platform_terms_accepted_at timestamptz"
    )
