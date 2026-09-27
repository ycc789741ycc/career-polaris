"""Evidence says what shape of work it is: one item, or a tally over many.

Three columns on ``profile.evidence``:

* ``granularity`` is ``item`` or ``summary``. Anything that counts work over
  time counts items only; a summary's date is just the latest of its items.
* ``tally`` is how many items a summary counts, so charts compare numbers
  rather than read them back out of a sentence.
* ``subject`` is the repository or project the work belongs to.

Existing rows are backfilled from the ``external_ref`` and ``reference`` shapes
the connectors write, so nobody has to re-sync to get correct charts. Every
other row, including résumé lines and answers, is an ``item`` with neither.

Written to be idempotent: the baseline migration builds tables from the live
ORM metadata, so on a fresh database the columns already exist.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0010_evidence_tallies"
down_revision: str | None = "0009_question_rounds"
branch_labels = None
depends_on = None

# Every pattern is bound rather than inlined: in a SQL string, ":merged" or
# ":project" reads as a parameter. Every summary sentence the connectors write
# starts with its count, which is where a tally comes from.
_BACKFILL: list[tuple[str, dict[str, str]]] = [
    (
        "UPDATE profile.evidence SET granularity = 'summary', "
        "tally = CAST(substring(fact FROM '^([0-9]+) ') AS integer), "
        "subject = substring(external_ref FROM :rest) "
        "WHERE source = 'github' AND external_ref LIKE :like",
        {"like": "github:merged:%", "rest": "^github:merged:(.+)$"},
    ),
    (
        "UPDATE profile.evidence SET granularity = 'summary', "
        "tally = CAST(substring(fact FROM '^([0-9]+) ') AS integer) "
        "WHERE source = 'github' AND external_ref = :like",
        {"like": "github:reviews"},
    ),
    (
        "UPDATE profile.evidence SET granularity = 'summary', "
        "tally = CAST(substring(fact FROM '^([0-9]+) ') AS integer) "
        "WHERE source = 'jira' AND external_ref LIKE :like",
        {"like": "jira:%:throughput"},
    ),
    (
        "UPDATE profile.evidence SET granularity = 'summary', "
        "tally = CAST(substring(fact FROM '^([0-9]+) ') AS integer), "
        "subject = substring(external_ref FROM :rest) "
        "WHERE source = 'jira' AND external_ref LIKE :like",
        {"like": "jira:%:project:%", "rest": ":project:(.+)$"},
    ),
    (
        "UPDATE profile.evidence SET subject = substring(reference FROM :rest) "
        "WHERE source = 'github' AND external_ref LIKE :like",
        {"like": "github:pr:%", "rest": "^GitHub · (.+)#[0-9]+$"},
    ),
    (
        "UPDATE profile.evidence SET subject = substring(reference FROM :rest) "
        "WHERE source = 'jira' AND external_ref LIKE :like",
        {"like": "jira:issue:%", "rest": "^Jira · ([^-]+)-"},
    ),
]


def upgrade() -> None:
    op.execute(
        "ALTER TABLE profile.evidence "
        "ADD COLUMN IF NOT EXISTS granularity varchar(16) NOT NULL DEFAULT 'item'"
    )
    op.execute("ALTER TABLE profile.evidence ADD COLUMN IF NOT EXISTS tally integer")
    op.execute("ALTER TABLE profile.evidence ADD COLUMN IF NOT EXISTS subject varchar(255)")
    op.execute("ALTER TABLE profile.evidence DROP CONSTRAINT IF EXISTS ck_evidence_granularity")
    op.execute(
        "ALTER TABLE profile.evidence ADD CONSTRAINT ck_evidence_granularity "
        "CHECK (granularity IN ('item', 'summary'))"
    )

    # The table forces row-level security even on its owner, and a migration
    # has no app.user_id, so an UPDATE here would see no rows at all. Lift the
    # force for the backfill only. It is all one transaction, and ALTER TABLE
    # holds an exclusive lock throughout, so no other session ever sees the
    # table without it.
    op.execute("ALTER TABLE profile.evidence NO FORCE ROW LEVEL SECURITY")
    for statement, params in _BACKFILL:
        op.execute(sa.text(statement).bindparams(**params))
    op.execute("ALTER TABLE profile.evidence FORCE ROW LEVEL SECURITY")

    # Added after the backfill, which is what first gives a summary its tally.
    op.execute("ALTER TABLE profile.evidence DROP CONSTRAINT IF EXISTS ck_evidence_tally")
    op.execute(
        "ALTER TABLE profile.evidence ADD CONSTRAINT ck_evidence_tally "
        "CHECK (tally IS NULL OR (granularity = 'summary' AND tally >= 0))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE profile.evidence DROP CONSTRAINT IF EXISTS ck_evidence_tally")
    op.execute("ALTER TABLE profile.evidence DROP CONSTRAINT IF EXISTS ck_evidence_granularity")
    op.execute("ALTER TABLE profile.evidence DROP COLUMN IF EXISTS subject")
    op.execute("ALTER TABLE profile.evidence DROP COLUMN IF EXISTS tally")
    op.execute("ALTER TABLE profile.evidence DROP COLUMN IF EXISTS granularity")
