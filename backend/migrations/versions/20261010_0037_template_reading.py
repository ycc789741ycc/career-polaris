"""A template can start from a PDF, read for its style only (ADR 0041).

Owner zone, under RLS: ``resume.template_reading``, one row per upload being
read: its status, where the file is until it is read, then the draft spec and
which of its values were read or defaulted. No text, name or font name of the
file is ever stored. A reading is deleted a day after its upload.

Idempotent, since the baseline migration builds tables from the live ORM
metadata. Downgrading drops the table; any file still waiting to be read is
left in object storage under ``users/{owner}/templatefiles/``.
"""

from __future__ import annotations

from alembic import op

revision: str = "0037_template_reading"
down_revision: str | None = "0036_custom_template"
branch_labels = None
depends_on = None

_APP_USER = "app.user_id"
_READING = "resume.template_reading"


def upgrade() -> None:
    op.execute(
        f"CREATE TABLE IF NOT EXISTS {_READING} ("
        " id uuid NOT NULL,"
        " owner_id uuid NOT NULL,"
        " status varchar(16) NOT NULL,"
        " storage_key varchar(512),"
        " spec jsonb,"
        " read_fields jsonb NOT NULL DEFAULT '[]'::jsonb,"
        " defaulted_fields jsonb NOT NULL DEFAULT '[]'::jsonb,"
        " error_code varchar(64),"
        " error_message text,"
        " created_at timestamptz NOT NULL DEFAULT now(),"
        " finished_at timestamptz,"
        " CONSTRAINT pk_template_reading PRIMARY KEY (id),"
        " CONSTRAINT ck_template_reading_status"
        "  CHECK (status IN ('reading', 'ready', 'failed'))"
        ")"
    )
    op.execute(f"CREATE INDEX IF NOT EXISTS ix_template_reading_owner_id ON {_READING} (owner_id)")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {_READING} TO app_rw")
    op.execute(f"ALTER TABLE {_READING} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {_READING} FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS owner_isolation ON {_READING}")
    op.execute(
        f"CREATE POLICY owner_isolation ON {_READING} FOR ALL "
        f"USING (owner_id::text = current_setting('{_APP_USER}', true)) "
        f"WITH CHECK (owner_id::text = current_setting('{_APP_USER}', true))"
    )


def downgrade() -> None:
    op.execute(f"DROP TABLE IF EXISTS {_READING}")
