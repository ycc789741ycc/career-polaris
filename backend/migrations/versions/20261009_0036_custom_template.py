"""Résumé templates of the user's own (ADR 0040).

Owner zone, under RLS:

* ``resume.custom_template``: a name and a checked spec (``TemplateSpec``,
  never markup), per user.
* ``resume.resume`` gains ``custom_template_id``; ``template`` becomes
  nullable, and the ``look`` check keeps exactly one of the two.
* ``resume.export`` gains ``spec``, the look it was rendered in, which reuse
  compares; ``template`` becomes nullable, since an export in a template of
  the user's own has no built-in one. Exports already stored have no spec and
  are never reused.

Written to be idempotent, since the baseline migration builds tables from the
live ORM metadata: on a fresh database every change is there already.

Downgrading moves every résumé and export in a template of the user's own to
Organic, then drops what was added. The templates themselves are lost.
"""

from __future__ import annotations

from alembic import op

revision: str = "0036_custom_template"
down_revision: str | None = "0035_resume_sections"
branch_labels = None
depends_on = None

_APP_USER = "app.user_id"
_TEMPLATE = "resume.custom_template"
_RESUME = "resume.resume"
_EXPORT = "resume.export"


def upgrade() -> None:
    op.execute(
        f"CREATE TABLE IF NOT EXISTS {_TEMPLATE} ("
        " id uuid NOT NULL,"
        " owner_id uuid NOT NULL,"
        " name varchar(60) NOT NULL,"
        " spec jsonb NOT NULL,"
        " created_at timestamptz NOT NULL DEFAULT now(),"
        " updated_at timestamptz NOT NULL DEFAULT now(),"
        " CONSTRAINT pk_custom_template PRIMARY KEY (id)"
        ")"
    )
    op.execute(f"CREATE INDEX IF NOT EXISTS ix_custom_template_owner_id ON {_TEMPLATE} (owner_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_custom_template_owner_created"
        f" ON {_TEMPLATE} (owner_id, created_at)"
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {_TEMPLATE} TO app_rw")
    op.execute(f"ALTER TABLE {_TEMPLATE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {_TEMPLATE} FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS owner_isolation ON {_TEMPLATE}")
    op.execute(
        f"CREATE POLICY owner_isolation ON {_TEMPLATE} FOR ALL "
        f"USING (owner_id::text = current_setting('{_APP_USER}', true)) "
        f"WITH CHECK (owner_id::text = current_setting('{_APP_USER}', true))"
    )

    op.execute(f"ALTER TABLE {_RESUME} ADD COLUMN IF NOT EXISTS custom_template_id uuid")
    op.execute(
        "DO $$ BEGIN "  # noqa: S608 - fixed table names, nothing interpolated from input
        "IF NOT EXISTS (SELECT 1 FROM pg_constraint"
        "  WHERE conname = 'fk_resume_custom_template_id_custom_template') THEN "
        f"ALTER TABLE {_RESUME} ADD CONSTRAINT fk_resume_custom_template_id_custom_template"
        f" FOREIGN KEY (custom_template_id) REFERENCES {_TEMPLATE} (id); "
        "END IF; "
        "END $$"
    )
    op.execute(f"ALTER TABLE {_RESUME} ALTER COLUMN template DROP NOT NULL")
    op.execute(f"ALTER TABLE {_RESUME} DROP CONSTRAINT IF EXISTS ck_resume_look")
    op.execute(
        f"ALTER TABLE {_RESUME} ADD CONSTRAINT ck_resume_look"
        " CHECK (num_nonnulls(template, custom_template_id) = 1)"
    )

    op.execute(f"ALTER TABLE {_EXPORT} ADD COLUMN IF NOT EXISTS spec jsonb")
    op.execute(f"ALTER TABLE {_EXPORT} ALTER COLUMN template DROP NOT NULL")


def downgrade() -> None:
    # FORCE ROW LEVEL SECURITY would hide every row from the migrator.
    for table in (_RESUME, _EXPORT):
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    op.execute("UPDATE resume.export SET template = 'organic' WHERE template IS NULL")
    op.execute(
        "UPDATE resume.resume SET template = 'organic', custom_template_id = NULL"
        " WHERE custom_template_id IS NOT NULL"
    )
    for table in (_RESUME, _EXPORT):
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")

    op.execute(f"ALTER TABLE {_EXPORT} ALTER COLUMN template SET NOT NULL")
    op.execute(f"ALTER TABLE {_EXPORT} DROP COLUMN IF EXISTS spec")
    op.execute(f"ALTER TABLE {_RESUME} DROP CONSTRAINT IF EXISTS ck_resume_look")
    op.execute(f"ALTER TABLE {_RESUME} ALTER COLUMN template SET NOT NULL")
    op.execute(f"ALTER TABLE {_RESUME} DROP COLUMN IF EXISTS custom_template_id")
    op.execute(f"DROP TABLE IF EXISTS {_TEMPLATE}")
