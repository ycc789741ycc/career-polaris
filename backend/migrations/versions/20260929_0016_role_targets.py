"""A Target is a role, plus an optional opening (domain decision 26, ADR 0022).

``gapplan.plan`` and ``resume.resume`` held a Target as a kind plus one
reference: a shared posting (``matchedPosting``) or a pasted JD
(``privatePosting``). Both now hold ``role_id`` and a nullable
``job_posting_id``:

* a plan or résumé for an opening keeps the opening, and takes the role its
  snapshot was frozen from;
* one for a pasted JD points at the custom role migration 0015 made from that
  JD, with no opening.

The stored snapshot's reference is rewritten to the same shape. A row whose
role cannot be found — a draft that failed before its snapshot was taken, or a
JD with no custom role — is deleted, with its versions, milestones and tasks
by cascade, and the migration says how many.

Written to be idempotent: the baseline migration builds tables from the live
ORM metadata, so on a fresh database the new columns already exist and the old
ones never did.

Downgrading restores the kind and the pasted-JD reference where the role is a
custom role with a JD, and deletes rows aimed at a role with no opening
otherwise: the old model had no way to hold them.
"""

from __future__ import annotations

import logging

from alembic import op
from sqlalchemy import text

revision: str = "0016_role_targets"
down_revision: str | None = "0015_custom_roles"
branch_labels = None
depends_on = None

log = logging.getLogger("alembic.runtime.migration")

# (table, constraint and index prefix) for each consumer that stores a Target.
_TARGET_TABLES = (("gapplan.plan", "plan"), ("resume.resume", "resume"))


def _has_column(table: str, column: str) -> bool:
    schema, _, name = table.partition(".")
    found = op.get_bind().execute(
        text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = :schema AND table_name = :name AND column_name = :column"
        ),
        {"schema": schema, "name": name, "column": column},
    )
    return found.first() is not None


def upgrade() -> None:
    bind = op.get_bind()
    for table, prefix in _TARGET_TABLES:
        if not _has_column(table, "target_kind"):
            continue  # a fresh database: built in the new shape already
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS role_id uuid")

        # Every table here is under FORCE ROW LEVEL SECURITY, which holds even
        # the owning migrator to the per-user policy. Lift it for the data step.
        # Table names are this module's constants, never input.
        for forced in (table, "rolemap.role"):
            op.execute(f"ALTER TABLE {forced} NO FORCE ROW LEVEL SECURITY")
        op.execute(
            f"UPDATE {table} SET role_id = (snapshot->>'role_id')::uuid "  # noqa: S608
            "WHERE target_kind = 'matchedPosting' AND snapshot->>'role_id' IS NOT NULL"
        )
        op.execute(
            f"UPDATE {table} t SET role_id = r.id, job_posting_id = NULL "  # noqa: S608
            "FROM rolemap.role r "
            "WHERE t.target_kind = 'privatePosting' "
            "AND r.private_posting_id = t.private_posting_id AND r.owner_id = t.owner_id"
        )
        op.execute(
            f"UPDATE {table} SET snapshot = (snapshot - 'kind' - 'id') || "  # noqa: S608
            "jsonb_build_object("
            "  'ref', jsonb_build_object('role_id', role_id::text, "
            "                            'job_posting_id', job_posting_id::text),"
            "  'role_id', role_id::text,"
            "  'role_name', coalesce(snapshot->>'role_name', snapshot->>'title')"
            ") WHERE snapshot IS NOT NULL AND role_id IS NOT NULL"
        )
        deleted = bind.execute(
            text(f"DELETE FROM {table} WHERE role_id IS NULL")  # noqa: S608
        ).rowcount
        for forced in (table, "rolemap.role"):
            op.execute(f"ALTER TABLE {forced} FORCE ROW LEVEL SECURITY")
        log.info("Deleted %s row(s) of %s whose role could not be found", deleted, table)

        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS ck_{prefix}_one_target")
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS ck_{prefix}_target_kind")
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS target_kind")
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS private_posting_id")
        op.execute(f"ALTER TABLE {table} ALTER COLUMN role_id SET NOT NULL")
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_{prefix}_role_id ON {table} (role_id)")


def downgrade() -> None:
    for table, prefix in _TARGET_TABLES:
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS target_kind varchar(16)")
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS private_posting_id uuid")
        for forced in (table, "rolemap.role"):
            op.execute(f"ALTER TABLE {forced} NO FORCE ROW LEVEL SECURITY")
        op.execute(
            f"UPDATE {table} SET target_kind = 'matchedPosting' "  # noqa: S608
            "WHERE job_posting_id IS NOT NULL"
        )
        op.execute(
            f"UPDATE {table} t SET target_kind = 'privatePosting', "  # noqa: S608
            "private_posting_id = r.private_posting_id "
            "FROM rolemap.role r "
            "WHERE t.job_posting_id IS NULL AND r.id = t.role_id "
            "AND r.private_posting_id IS NOT NULL"
        )
        op.execute(f"DELETE FROM {table} WHERE target_kind IS NULL")  # noqa: S608
        op.execute(
            f"UPDATE {table} SET snapshot = (snapshot - 'ref') || jsonb_build_object("  # noqa: S608
            "  'kind', target_kind,"
            "  'id', coalesce(job_posting_id, private_posting_id)::text"
            ") WHERE snapshot IS NOT NULL"
        )
        for forced in (table, "rolemap.role"):
            op.execute(f"ALTER TABLE {forced} FORCE ROW LEVEL SECURITY")
        op.execute(f"DROP INDEX IF EXISTS {table.partition('.')[0]}.ix_{prefix}_role_id")
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS role_id")
        op.execute(f"ALTER TABLE {table} ALTER COLUMN target_kind SET NOT NULL")
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT ck_{prefix}_one_target "
            "CHECK (num_nonnulls(job_posting_id, private_posting_id) = 1)"
        )
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT ck_{prefix}_target_kind "
            "CHECK (target_kind IN ('matchedPosting', 'privatePosting'))"
        )
