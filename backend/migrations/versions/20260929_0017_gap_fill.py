"""Fill the gap replaces follow-up questions (domain decision 27, ADR 0023).

* ``gapfill.question_set`` / ``gapfill.question``: owner zone, under RLS. A set
  is keyed on its Target (a role, and optionally one opening in it) and has a
  status the page polls; each question keeps its gap, "asked because", answer
  type and choices, and the evidence id its submitted answer became.
* ``assessment.follow_up_question`` and ``assessment.question_round`` are
  dropped: questions no longer come from a low-confidence radar.
* ``profile.evidence.source`` ``self_reported`` becomes ``user_answer``
  ("Your answers"). The answers already given stay evidence.
* ``resume.version.source`` gains ``answers``: a résumé written again after
  answers were submitted.

Written to be idempotent: the baseline migration builds tables from the live
ORM metadata, so on a fresh database the new tables already exist, with their
policies. The baseline's grants list its schemas by name, so the grants for
``gapfill`` are made here.

Downgrading restores the question tables empty, turns ``user_answer`` evidence
back into ``self_reported``, and drops the gapfill schema with the questions
written in it.
"""

from __future__ import annotations

import logging

from alembic import op
from sqlalchemy import text

revision: str = "0017_gap_fill"
down_revision: str | None = "0016_role_targets"
branch_labels = None
depends_on = None

log = logging.getLogger("alembic.runtime.migration")

_APP_USER = "app.user_id"
_TABLES = ("gapfill.question_set", "gapfill.question")


def _owner_isolation(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS owner_isolation ON {table}")
    op.execute(
        f"CREATE POLICY owner_isolation ON {table} FOR ALL "
        f"USING (owner_id::text = current_setting('{_APP_USER}', true)) "
        f"WITH CHECK (owner_id::text = current_setting('{_APP_USER}', true))"
    )


def upgrade() -> None:
    op.execute('CREATE SCHEMA IF NOT EXISTS "gapfill"')
    op.execute('GRANT USAGE ON SCHEMA "gapfill" TO app_rw')
    op.execute(
        "CREATE TABLE IF NOT EXISTS gapfill.question_set ("
        " id uuid NOT NULL,"
        " owner_id uuid NOT NULL,"
        " role_id uuid NOT NULL,"
        " job_posting_id uuid,"
        " label varchar(400) NOT NULL,"
        " status varchar(16) NOT NULL,"
        " gaps jsonb NOT NULL DEFAULT '[]'::jsonb,"
        " model_id varchar(128),"
        " template_version varchar(128),"
        " error_code varchar(64),"
        " error_message text,"
        " created_at timestamptz NOT NULL DEFAULT now(),"
        " written_at timestamptz,"
        " submitted_at timestamptz,"
        " CONSTRAINT pk_question_set PRIMARY KEY (id),"
        " CONSTRAINT ck_question_set_status"
        " CHECK (status IN ('writing', 'ready', 'failed', 'superseded'))"
        ")"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_question_set_owner_id ON gapfill.question_set (owner_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_question_set_role_id ON gapfill.question_set (role_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_question_set_owner_created "
        "ON gapfill.question_set (owner_id, created_at)"
    )
    op.execute(
        "CREATE TABLE IF NOT EXISTS gapfill.question ("
        " id uuid NOT NULL,"
        " owner_id uuid NOT NULL,"
        " set_id uuid NOT NULL,"
        " position integer NOT NULL,"
        " gap_key varchar(128) NOT NULL,"
        " gap_label varchar(400) NOT NULL,"
        " gap_status varchar(16) NOT NULL,"
        " lift integer NOT NULL,"
        " text text NOT NULL,"
        " asked_because text NOT NULL,"
        " answer_type varchar(16) NOT NULL,"
        " choices jsonb NOT NULL DEFAULT '[]'::jsonb,"
        " evidence_id uuid,"
        " answered_at timestamptz,"
        " CONSTRAINT pk_question PRIMARY KEY (id),"
        " CONSTRAINT fk_question_set_id_question_set FOREIGN KEY (set_id)"
        " REFERENCES gapfill.question_set (id) ON DELETE CASCADE,"
        " CONSTRAINT ck_question_answer_type"
        " CHECK (answer_type IN ('choice', 'free_text', 'both')),"
        " CONSTRAINT ck_question_gap_status CHECK (gap_status IN ('partial', 'no_evidence'))"
        ")"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_question_owner_id ON gapfill.question (owner_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_question_set_id ON gapfill.question (set_id)")
    op.execute('GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA "gapfill" TO app_rw')
    op.execute(
        'ALTER DEFAULT PRIVILEGES IN SCHEMA "gapfill" '
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_rw"
    )
    for table in _TABLES:
        _owner_isolation(table)

    op.execute("DROP TABLE IF EXISTS assessment.follow_up_question")
    op.execute("DROP TABLE IF EXISTS assessment.question_round")

    # The evidence is owner-zone under FORCE ROW LEVEL SECURITY, which holds
    # even the owning migrator to the per-user policy; lift it for the rename.
    op.execute("ALTER TABLE profile.evidence NO FORCE ROW LEVEL SECURITY")
    renamed = (
        op.get_bind()
        .execute(
            text(
                "UPDATE profile.evidence SET source = 'user_answer' WHERE source = 'self_reported'"
            )
        )
        .rowcount
    )
    op.execute("ALTER TABLE profile.evidence FORCE ROW LEVEL SECURITY")
    log.info("Renamed %s answer(s) from self_reported to user_answer", renamed)

    op.execute("ALTER TABLE resume.version DROP CONSTRAINT IF EXISTS ck_version_source")
    op.execute(
        "ALTER TABLE resume.version ADD CONSTRAINT ck_version_source "
        "CHECK (source IN ('generated', 'manual', 'chat', 'answers'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE resume.version NO FORCE ROW LEVEL SECURITY")
    op.execute("UPDATE resume.version SET source = 'generated' WHERE source = 'answers'")
    op.execute("ALTER TABLE resume.version FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE resume.version DROP CONSTRAINT IF EXISTS ck_version_source")
    op.execute(
        "ALTER TABLE resume.version ADD CONSTRAINT ck_version_source "
        "CHECK (source IN ('generated', 'manual', 'chat'))"
    )

    op.execute("ALTER TABLE profile.evidence NO FORCE ROW LEVEL SECURITY")
    op.execute("UPDATE profile.evidence SET source = 'self_reported' WHERE source = 'user_answer'")
    op.execute("ALTER TABLE profile.evidence FORCE ROW LEVEL SECURITY")

    op.execute(
        "CREATE TABLE IF NOT EXISTS assessment.question_round ("
        " id uuid NOT NULL,"
        " owner_id uuid NOT NULL,"
        " assessment_id uuid NOT NULL,"
        " trigger varchar(16) NOT NULL,"
        " status varchar(16) NOT NULL,"
        " question_count integer NOT NULL DEFAULT 0,"
        " error_code varchar(64),"
        " error_message text,"
        " created_at timestamptz NOT NULL DEFAULT now(),"
        " finished_at timestamptz,"
        " CONSTRAINT pk_question_round PRIMARY KEY (id)"
        ")"
    )
    op.execute(
        "CREATE TABLE IF NOT EXISTS assessment.follow_up_question ("
        " id uuid NOT NULL,"
        " owner_id uuid NOT NULL,"
        " assessment_id uuid NOT NULL,"
        " dimension_key varchar(128) NOT NULL,"
        " text text NOT NULL,"
        " why text NOT NULL,"
        " options jsonb NOT NULL DEFAULT '[]'::jsonb,"
        " answer text,"
        " answered_at timestamptz,"
        " retired_at timestamptz,"
        " created_at timestamptz NOT NULL DEFAULT now(),"
        " CONSTRAINT pk_follow_up_question PRIMARY KEY (id)"
        ")"
    )
    for table in ("assessment.question_round", "assessment.follow_up_question"):
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO app_rw")
        _owner_isolation(table)

    for table in reversed(_TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table}")
    op.execute('DROP SCHEMA IF EXISTS "gapfill"')
