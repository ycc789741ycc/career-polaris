"""Advisor jobs record their stage and can be cancelled (ADR 0042).

The four rows an Advisor job runs on — ``gapfill.question_set``,
``gapplan.plan``, ``resume.resume`` and ``target.posting_evaluation`` — gain
``stage`` and ``progress`` (0 to 1), and each status check takes ``cancelled``.
The first three also gain ``estimated_cost_usd``, the priced cost of the call
being made; a posting's evaluation calls through the role map's kit and has
none.

Idempotent, since the baseline migration builds tables from the live ORM
metadata. Downgrading turns every cancelled row into the nearest older status
— a question set superseded, a plan, résumé or evaluation failed with the
reason — and drops the columns.
"""

from __future__ import annotations

from alembic import op

revision: str = "0038_advisor_jobs"
down_revision: str | None = "0037_template_reading"
branch_labels = None
depends_on = None

# table, its status check, the statuses before this migration, cost column?
_TABLES = (
    (
        "gapfill.question_set",
        "ck_question_set_status",
        "'writing', 'ready', 'failed', 'superseded'",
        True,
    ),
    ("gapplan.plan", "ck_plan_status", "'drafting', 'ready', 'failed'", True),
    ("resume.resume", "ck_resume_status", "'drafting', 'ready', 'failed', 'filling'", True),
    (
        "target.posting_evaluation",
        "ck_posting_evaluation_status",
        "'running', 'ready', 'failed'",
        False,
    ),
)

_CANCELLED_BEFORE = {
    "gapfill.question_set": "status = 'superseded'",
    "gapplan.plan": "status = 'failed', error_code = 'cancelled',"
    " error_message = 'Stopped before it was drafted.'",
    "resume.resume": "status = 'failed', error_code = 'cancelled',"
    " error_message = 'Stopped before it was written.'",
    "target.posting_evaluation": "status = 'failed', error_code = 'cancelled',"
    " error_message = 'Stopped before it was scored.'",
}


def upgrade() -> None:
    for table, check, statuses, has_cost in _TABLES:
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS stage varchar(24)")
        op.execute(
            f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS progress double precision"
            " NOT NULL DEFAULT 0"
        )
        if has_cost:
            op.execute(
                f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS estimated_cost_usd numeric(12, 6)"
            )
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {check}")
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT {check}"
            f" CHECK (status IN ({statuses}, 'cancelled'))"
        )


def downgrade() -> None:
    for table, check, statuses, has_cost in _TABLES:
        # FORCE ROW LEVEL SECURITY would hide every row from the migrator.
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(
            f"UPDATE {table} SET {_CANCELLED_BEFORE[table]} WHERE status = 'cancelled'"  # noqa: S608 - fixed names
        )
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {check}")
        op.execute(f"ALTER TABLE {table} ADD CONSTRAINT {check} CHECK (status IN ({statuses}))")
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS stage")
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS progress")
        if has_cost:
            op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS estimated_cost_usd")
