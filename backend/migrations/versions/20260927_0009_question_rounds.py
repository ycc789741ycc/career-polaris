"""Follow-up questions generated in the background, in rounds (ADR 0012).

* ``assessment.question_round``: owner zone, under RLS. One row per request to
  generate questions, created before the job runs so the page can show that
  questions are being generated (ADR 0006).
* ``assessment.follow_up_question.retired_at``: set when a newer round
  replaces a question nobody answered.

Written to be idempotent: the baseline migration builds tables from the live
ORM metadata, so on a fresh database these already exist, with their policy,
by the time this revision runs.
"""

from __future__ import annotations

from alembic import op

revision: str = "0009_question_rounds"
down_revision: str | None = "0008_federated_identity"
branch_labels = None
depends_on = None

_APP_USER = "app.user_id"
_TABLE = "assessment.question_round"


def upgrade() -> None:
    op.execute(
        "ALTER TABLE assessment.follow_up_question ADD COLUMN IF NOT EXISTS retired_at timestamptz"
    )

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
        " CONSTRAINT pk_question_round PRIMARY KEY (id),"
        " CONSTRAINT fk_question_round_assessment_id_skill_assessment"
        " FOREIGN KEY (assessment_id)"
        " REFERENCES assessment.skill_assessment (id) ON DELETE CASCADE"
        ")"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_question_round_owner_id "
        "ON assessment.question_round (owner_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_question_round_owner_created "
        "ON assessment.question_round (owner_id, created_at)"
    )

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
    op.execute("ALTER TABLE assessment.follow_up_question DROP COLUMN IF EXISTS retired_at")
