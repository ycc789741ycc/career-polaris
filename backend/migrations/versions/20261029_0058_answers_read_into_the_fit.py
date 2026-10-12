"""Submitted answers are read into the Target's fit (ADR 0077).

* ``gapfill.question_set`` gains ``fit_reading`` (null until submitted, then
  ``reading``, ``ready``, ``failed`` or ``cancelled``, checked) and its error
  code and message.
* ``target.answer_reading``, owner zone, under RLS, with no grant to the
  crawler: what the answers say about one gap of one Target — a dimension's
  score or a requirement's coverage — with the answers it cites and the
  analysis it was taken against.

Nothing stored changes: a set submitted before this has no reading, and its
Target's fit stays as the analysis scored it until its answers are read.

Idempotent: the baseline builds tables from the live ORM metadata, so on a
fresh database the table and columns already exist and only the grants and
the policy are new. Downgrading drops the table and the columns.
"""

from __future__ import annotations

from alembic import op

revision: str = "0058_answers_read_into_the_fit"
down_revision: str | None = "0057_resume_own_look"
branch_labels = None
depends_on = None

_APP_USER = "app.user_id"
_SET = "gapfill.question_set"
_READING = "target.answer_reading"


def upgrade() -> None:
    op.execute(f"ALTER TABLE {_SET} ADD COLUMN IF NOT EXISTS fit_reading varchar(16)")
    op.execute(f"ALTER TABLE {_SET} ADD COLUMN IF NOT EXISTS fit_reading_error_code varchar(64)")
    op.execute(f"ALTER TABLE {_SET} ADD COLUMN IF NOT EXISTS fit_reading_error_message text")
    op.execute(f"ALTER TABLE {_SET} DROP CONSTRAINT IF EXISTS ck_question_set_fit_reading")
    op.execute(
        f"ALTER TABLE {_SET} ADD CONSTRAINT ck_question_set_fit_reading CHECK"
        " (fit_reading IS NULL OR fit_reading IN ('reading', 'ready', 'failed', 'cancelled'))"
    )

    op.execute(
        f"CREATE TABLE IF NOT EXISTS {_READING} ("
        " id uuid NOT NULL,"
        " owner_id uuid NOT NULL,"
        " role_id uuid,"
        " job_posting_id uuid,"
        " private_job_posting_id uuid,"
        " question_set_id uuid NOT NULL,"
        " assessment_id uuid NOT NULL,"
        " gap_key varchar(128) NOT NULL,"
        " score integer,"
        " coverage varchar(16),"
        " reasoning text NOT NULL,"
        " evidence_ids jsonb NOT NULL,"
        " model_id varchar(128) NOT NULL,"
        " template_version varchar(128) NOT NULL,"
        " created_at timestamptz NOT NULL DEFAULT now(),"
        " CONSTRAINT pk_answer_reading PRIMARY KEY (id),"
        " CONSTRAINT ck_answer_reading_target"
        " CHECK (num_nonnulls(role_id, private_job_posting_id) = 1),"
        " CONSTRAINT ck_answer_reading_reading CHECK (num_nonnulls(score, coverage) = 1),"
        " CONSTRAINT ck_answer_reading_score CHECK (score IS NULL OR score BETWEEN 0 AND 100),"
        " CONSTRAINT ck_answer_reading_coverage"
        " CHECK (coverage IS NULL OR coverage IN ('covered', 'partly', 'not'))"
        ")"
    )
    op.execute(f"CREATE INDEX IF NOT EXISTS ix_answer_reading_owner_id ON {_READING} (owner_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_answer_reading_owner_created"
        f" ON {_READING} (owner_id, created_at)"
    )
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
    op.execute(f"ALTER TABLE {_SET} DROP CONSTRAINT IF EXISTS ck_question_set_fit_reading")
    for column in ("fit_reading_error_message", "fit_reading_error_code", "fit_reading"):
        op.execute(f"ALTER TABLE {_SET} DROP COLUMN IF EXISTS {column}")
