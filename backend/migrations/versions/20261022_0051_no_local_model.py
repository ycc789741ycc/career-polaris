"""There is no self-hosted model option (ADR 0065).

A hosted service cannot reach a model on the user's machine, so a ``local``
credential could never be used. ``identity.provider_credential`` loses those
rows: their owners are asked for a key again, as before they set one. A base
URL stays only for an OpenAI key, which may name an OpenAI-compatible cloud;
one stored for another provider is cleared. Two checks keep it so.

Forward-only in practice: downgrading drops the checks, but the deleted
credentials are gone.
"""

from __future__ import annotations

from alembic import op

revision: str = "0051_no_local_model"
down_revision: str | None = "0050_ai_source_choice"
branch_labels = None
depends_on = None

_TABLE = "identity.provider_credential"


def upgrade() -> None:
    # FORCE ROW LEVEL SECURITY holds even the owning migrator to the per-user
    # policy, so it is lifted while every owner's rows are changed, and
    # restored after (as migration 0030 does).
    op.execute(f"ALTER TABLE {_TABLE} NO FORCE ROW LEVEL SECURITY")
    op.execute("DELETE FROM identity.provider_credential WHERE provider = 'local'")
    op.execute(
        "UPDATE identity.provider_credential SET base_url = NULL WHERE provider <> 'openai'"
    )
    op.execute(f"ALTER TABLE {_TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {_TABLE} DROP CONSTRAINT IF EXISTS ck_provider_credential_provider")
    op.execute(
        f"ALTER TABLE {_TABLE} ADD CONSTRAINT ck_provider_credential_provider"
        " CHECK (provider IN ('anthropic', 'openai', 'google'))"
    )
    op.execute(f"ALTER TABLE {_TABLE} DROP CONSTRAINT IF EXISTS ck_provider_credential_base_url")
    op.execute(
        f"ALTER TABLE {_TABLE} ADD CONSTRAINT ck_provider_credential_base_url"
        " CHECK (base_url IS NULL OR provider = 'openai')"
    )


def downgrade() -> None:
    op.execute(f"ALTER TABLE {_TABLE} DROP CONSTRAINT IF EXISTS ck_provider_credential_base_url")
    op.execute(f"ALTER TABLE {_TABLE} DROP CONSTRAINT IF EXISTS ck_provider_credential_provider")
