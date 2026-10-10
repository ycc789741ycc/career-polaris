"""Which key a user's AI runs on, once they have chosen (ADR 0064).

``identity.ai_source_choice`` holds one row per account that has chosen:
``own`` or ``platform``, and when it accepted that its evidence goes to the
operator's provider. No row means the user's own key, if they stored one.
Owner zone: row-level security keyed on ``app.user_id``, as every identity
table the owner holds.

Idempotent: the baseline builds tables from the live ORM metadata, so on a
fresh database the table already exists, and only the grant and the policy
are new.
"""

from __future__ import annotations

from alembic import op

revision: str = "0050_ai_source_choice"
down_revision: str | None = "0049_platform_ai_spend"
branch_labels = None
depends_on = None

_APP_USER = "app.user_id"
_TABLE = "identity.ai_source_choice"


def upgrade() -> None:
    op.execute(
        f"CREATE TABLE IF NOT EXISTS {_TABLE} ("
        " id uuid NOT NULL,"
        " owner_id uuid NOT NULL,"
        " source varchar(16) NOT NULL,"
        " platform_terms_accepted_at timestamptz,"
        " created_at timestamptz NOT NULL DEFAULT now(),"
        " updated_at timestamptz NOT NULL DEFAULT now(),"
        " CONSTRAINT pk_ai_source_choice PRIMARY KEY (id),"
        " CONSTRAINT uq_ai_source_choice_owner_id UNIQUE (owner_id),"
        " CONSTRAINT ck_ai_source_choice_source CHECK (source IN ('own', 'platform'))"
        ")"
    )
    op.execute(f"CREATE INDEX IF NOT EXISTS ix_ai_source_choice_owner_id ON {_TABLE} (owner_id)")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {_TABLE} TO app_rw")
    op.execute(f"ALTER TABLE {_TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {_TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS owner_isolation ON {_TABLE}")
    op.execute(
        f"CREATE POLICY owner_isolation ON {_TABLE} FOR ALL "
        f"USING (owner_id::text = current_setting('{_APP_USER}', true)) "
        f"WITH CHECK (owner_id::text = current_setting('{_APP_USER}', true))"
    )


def downgrade() -> None:
    op.execute(f"DROP TABLE IF EXISTS {_TABLE}")
