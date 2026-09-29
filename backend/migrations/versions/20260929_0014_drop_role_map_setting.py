"""The role map analyses ten roles, fixed by the system (domain decision 23, ADR 0020).

``rolemap.role_map_setting`` held each user's own count, which is gone. Nothing
replaces it: the count is a constant in the ``rolemap`` domain.

On a fresh database migration 0003 still creates the table, and this drops it.

Downgrading restores the table, empty: every user falls back to the old
default of ten, which is the count they have now anyway.
"""

from __future__ import annotations

from alembic import op

revision: str = "0014_drop_role_map_setting"
down_revision: str | None = "0013_drop_role_subscriptions"
branch_labels = None
depends_on = None

_APP_USER = "app.user_id"


def upgrade() -> None:
    # Dropping the table drops its policy and constraints with it.
    op.execute("DROP TABLE IF EXISTS rolemap.role_map_setting")


def downgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS rolemap.role_map_setting (
            id uuid NOT NULL,
            owner_id uuid NOT NULL,
            role_count integer NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT pk_role_map_setting PRIMARY KEY (id),
            CONSTRAINT uq_role_map_setting_owner_id UNIQUE (owner_id),
            CONSTRAINT ck_role_map_setting_role_count CHECK (role_count BETWEEN 3 AND 20)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_role_map_setting_owner_id "
        "ON rolemap.role_map_setting (owner_id)"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON rolemap.role_map_setting TO app_rw")
    op.execute("ALTER TABLE rolemap.role_map_setting ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE rolemap.role_map_setting FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY owner_isolation ON rolemap.role_map_setting FOR ALL "
        f"USING (owner_id::text = current_setting('{_APP_USER}', true)) "
        f"WITH CHECK (owner_id::text = current_setting('{_APP_USER}', true))"
    )
