"""A posting of the user's own is a Target, not a role (Phase 8, ADR 0030).

Owner zone, under RLS:

* ``rolemap.posting_evaluation``, ``rolemap.posting_requirement``,
  ``rolemap.posting_requirement_fit`` and ``rolemap.posting_fit``: a posting of
  the user's own, the run that reads and scores it, its requirements, the AI's
  evaluation of them, and the fit worked out from that locally.
* ``gapplan.plan``, ``resume.resume`` and ``gapfill.question_set`` gain
  ``private_job_posting_id``, and ``role_id`` becomes nullable: a Target is a
  role (and optionally an opening), or a posting of the user's own, exactly
  one of the two.
* Each custom role with a pasted JD becomes a posting of the user's own: its
  requirements, its latest fit and a finished run are copied over, and the
  plans, résumés and question sets aimed at it are pointed at the posting.
  Then every custom role is retired, and its members dropped so a later build
  cannot reconcile a recommended role into it. A custom role without a JD is
  only retired; what was aimed at it stays as history, like any retired role.
* ``rolemap.role`` loses ``origin``, ``company_name`` and
  ``private_posting_id``.

FORCE ROW LEVEL SECURITY holds even the owning migrator to the per-user policy,
so it is lifted on the tables read and written here, and restored after.

Written to be idempotent, since the baseline migration builds tables from the
live ORM metadata: on a fresh database the new tables and columns already
exist, and ``rolemap.role`` never had the custom-role columns. Since ADR 0033
a fresh database has no ``market_user.private_job_posting`` either, and so no
custom role to move.

Downgrading drops the new tables and columns and gives ``rolemap.role`` its
columns back, every role ``recommended``. It cannot turn postings back into
custom roles, and leaves ``role_id`` nullable: rows aimed at a posting have
none to give it.
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision: str = "0025_own_posting_target"
down_revision: str | None = "0024_retire_merged_roles"
branch_labels = None
depends_on = None

_APP_USER = "app.user_id"
_EVALUATION = "rolemap.posting_evaluation"
_REQUIREMENT = "rolemap.posting_requirement"
_REQUIREMENT_FIT = "rolemap.posting_requirement_fit"
_POSTING_FIT = "rolemap.posting_fit"
_NEW = (_EVALUATION, _REQUIREMENT, _REQUIREMENT_FIT, _POSTING_FIT)
# (table, the name its check constraint gets from the naming convention)
_AIMED = (
    ("gapplan.plan", "ck_plan_target"),
    ("resume.resume", "ck_resume_target"),
    ("gapfill.question_set", "ck_question_set_target"),
)
_READ = (
    "rolemap.role",
    "rolemap.role_member",
    "rolemap.role_requirement",
    "rolemap.role_fit",
    "market_user.private_job_posting",
)


def upgrade() -> None:
    _create_tables()
    for table, _constraint in _AIMED:
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS private_job_posting_id uuid")
        op.execute(f"ALTER TABLE {table} ALTER COLUMN role_id DROP NOT NULL")

    tables = tuple(
        table
        for table in (*_NEW, *(table for table, _ in _AIMED), *_READ)
        if op.get_bind().execute(text("SELECT to_regclass(:t)"), {"t": table}).scalar()
    )
    _lift_force(tables)
    op.execute(
        "DO $$ BEGIN "  # noqa: S608
        "IF EXISTS (SELECT 1 FROM information_schema.columns"
        "  WHERE table_schema = 'rolemap' AND table_name = 'role'"
        "  AND column_name = 'private_posting_id')"
        " AND to_regclass('market_user.private_job_posting') IS NOT NULL THEN "
        f"{_MOVE_CUSTOM_ROLES}"
        "END IF; "
        "END $$"
    )
    _restore_force(tables)

    for table, constraint in _AIMED:
        op.execute(
            "DO $$ BEGIN "  # noqa: S608
            f"IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = '{constraint}') THEN "
            f"  ALTER TABLE {table} ADD CONSTRAINT {constraint}"
            "   CHECK (num_nonnulls(role_id, private_job_posting_id) = 1); "
            "END IF; "
            "END $$"
        )
    op.execute("ALTER TABLE rolemap.role DROP CONSTRAINT IF EXISTS ck_role_origin")
    op.execute("ALTER TABLE rolemap.role DROP COLUMN IF EXISTS origin")
    op.execute("ALTER TABLE rolemap.role DROP COLUMN IF EXISTS company_name")
    op.execute("ALTER TABLE rolemap.role DROP COLUMN IF EXISTS private_posting_id")


# Each custom role whose pasted JD still exists becomes a posting of the user's
# own. The role's latest fit keeps its id as the posting's AI fit, so the
# posting fit can name it, and a second run inserts nothing twice.
_MOVE_CUSTOM_ROLES = (
    "CREATE TEMP TABLE _moved ON COMMIT DROP AS"
    " SELECT r.id AS role_id, r.owner_id, r.private_posting_id AS posting_id,"
    "  r.created_at"
    " FROM rolemap.role AS r"
    " JOIN market_user.private_job_posting AS p ON p.id = r.private_posting_id"
    " WHERE r.origin = 'custom'; "
    "INSERT INTO rolemap.posting_requirement"
    " (id, owner_id, private_job_posting_id, statement, weight, expected_level)"
    " SELECT gen_random_uuid(), m.owner_id, m.posting_id, q.statement, q.weight,"
    "  q.expected_level"
    " FROM _moved AS m JOIN rolemap.role_requirement AS q ON q.role_id = m.role_id"
    " WHERE NOT EXISTS (SELECT 1 FROM rolemap.posting_requirement AS e"
    "  WHERE e.private_job_posting_id = m.posting_id); "
    "INSERT INTO rolemap.posting_requirement_fit"
    " (id, owner_id, private_job_posting_id, assessment_id, requirements,"
    "  requirement_map, target_profile, reasoning, model_id, template_version, created_at)"
    " SELECT f.id, m.owner_id, m.posting_id, f.assessment_id, f.requirements,"
    "  f.requirement_map, f.target_profile, f.reasoning, f.model_id, f.template_version,"
    "  f.created_at"
    " FROM _moved AS m"
    " JOIN LATERAL (SELECT * FROM rolemap.role_fit AS rf WHERE rf.role_id = m.role_id"
    "  ORDER BY rf.created_at DESC LIMIT 1) AS f ON true"
    " ON CONFLICT (id) DO NOTHING; "
    "INSERT INTO rolemap.posting_fit"
    " (id, owner_id, posting_key, basis, source_fit_id, assessment_id, score,"
    "  requirements, requirement_map, target_profile, gaps, uncovered, created_at)"
    " SELECT gen_random_uuid(), m.owner_id, 'private:' || m.posting_id::text, 'own', f.id,"
    "  f.assessment_id, f.score, f.requirements, f.requirement_map, f.target_profile,"
    "  f.gaps, f.uncovered, f.created_at"
    " FROM _moved AS m"
    " JOIN LATERAL (SELECT * FROM rolemap.role_fit AS rf WHERE rf.role_id = m.role_id"
    "  ORDER BY rf.created_at DESC LIMIT 1) AS f ON true"
    " WHERE NOT EXISTS (SELECT 1 FROM rolemap.posting_fit AS e"
    "  WHERE e.posting_key = 'private:' || m.posting_id::text); "
    "INSERT INTO rolemap.posting_evaluation"
    " (id, owner_id, private_job_posting_id, status, reads_requirements, requested_at,"
    "  finished_at)"
    " SELECT gen_random_uuid(), m.owner_id, m.posting_id, 'ready', true, m.created_at, now()"
    " FROM _moved AS m"
    " WHERE NOT EXISTS (SELECT 1 FROM rolemap.posting_evaluation AS e"
    "  WHERE e.private_job_posting_id = m.posting_id); "
    "UPDATE gapplan.plan AS t SET private_job_posting_id = m.posting_id,"
    " role_id = NULL, job_posting_id = NULL FROM _moved AS m WHERE t.role_id = m.role_id; "
    "UPDATE resume.resume AS t SET private_job_posting_id = m.posting_id,"
    " role_id = NULL, job_posting_id = NULL FROM _moved AS m WHERE t.role_id = m.role_id; "
    "UPDATE gapfill.question_set AS t SET private_job_posting_id = m.posting_id,"
    " role_id = NULL, job_posting_id = NULL FROM _moved AS m WHERE t.role_id = m.role_id; "
    "DELETE FROM rolemap.role_member AS rm USING rolemap.role AS r"
    " WHERE rm.role_id = r.id AND r.origin = 'custom'; "
    "UPDATE rolemap.role SET retired_at = now()"
    " WHERE origin = 'custom' AND retired_at IS NULL; "
)


def downgrade() -> None:
    op.execute("ALTER TABLE rolemap.role ADD COLUMN IF NOT EXISTS origin varchar(16)")
    op.execute("UPDATE rolemap.role SET origin = 'recommended' WHERE origin IS NULL")
    op.execute("ALTER TABLE rolemap.role ALTER COLUMN origin SET DEFAULT 'recommended'")
    op.execute("ALTER TABLE rolemap.role ALTER COLUMN origin SET NOT NULL")
    op.execute("ALTER TABLE rolemap.role ADD COLUMN IF NOT EXISTS company_name varchar(255)")
    op.execute("ALTER TABLE rolemap.role ADD COLUMN IF NOT EXISTS private_posting_id uuid")
    op.execute(
        "DO $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_role_origin') THEN "
        "  ALTER TABLE rolemap.role ADD CONSTRAINT ck_role_origin"
        "   CHECK (origin IN ('recommended', 'custom')); "
        "END IF; "
        "END $$"
    )
    for table, constraint in _AIMED:
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {constraint}")
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS private_job_posting_id")
    for table in reversed(_NEW):
        op.execute(f"DROP TABLE IF EXISTS {table}")


def _create_tables() -> None:
    op.execute(
        f"CREATE TABLE IF NOT EXISTS {_EVALUATION} ("
        " id uuid NOT NULL,"
        " owner_id uuid NOT NULL,"
        " private_job_posting_id uuid NOT NULL,"
        " status varchar(16) NOT NULL,"
        " reads_requirements boolean NOT NULL,"
        " error_code varchar(64),"
        " error_message text,"
        " requested_at timestamptz NOT NULL DEFAULT now(),"
        " finished_at timestamptz,"
        " CONSTRAINT pk_posting_evaluation PRIMARY KEY (id),"
        " CONSTRAINT ck_posting_evaluation_status"
        "  CHECK (status IN ('running', 'ready', 'failed'))"
        ")"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_posting_evaluation_owner_posting"
        f" ON {_EVALUATION} (owner_id, private_job_posting_id, requested_at)"
    )
    op.execute(
        f"CREATE TABLE IF NOT EXISTS {_REQUIREMENT} ("
        " id uuid NOT NULL,"
        " owner_id uuid NOT NULL,"
        " private_job_posting_id uuid NOT NULL,"
        " statement text NOT NULL,"
        " weight double precision NOT NULL,"
        " expected_level varchar(32) NOT NULL,"
        " CONSTRAINT pk_posting_requirement PRIMARY KEY (id)"
        ")"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_posting_requirement_private_job_posting_id"
        f" ON {_REQUIREMENT} (private_job_posting_id)"
    )
    op.execute(
        f"CREATE TABLE IF NOT EXISTS {_REQUIREMENT_FIT} ("
        " id uuid NOT NULL,"
        " owner_id uuid NOT NULL,"
        " private_job_posting_id uuid NOT NULL,"
        " assessment_id uuid NOT NULL,"
        " requirements jsonb NOT NULL,"
        " requirement_map jsonb NOT NULL,"
        " target_profile jsonb NOT NULL,"
        " reasoning text NOT NULL,"
        " model_id varchar(128) NOT NULL,"
        " template_version varchar(128) NOT NULL,"
        " created_at timestamptz NOT NULL DEFAULT now(),"
        " CONSTRAINT pk_posting_requirement_fit PRIMARY KEY (id)"
        ")"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_posting_requirement_fit_owner_posting"
        f" ON {_REQUIREMENT_FIT} (owner_id, private_job_posting_id, created_at)"
    )
    op.execute(
        f"CREATE TABLE IF NOT EXISTS {_POSTING_FIT} ("
        " id uuid NOT NULL,"
        " owner_id uuid NOT NULL,"
        " posting_key varchar(128) NOT NULL,"
        " basis varchar(8) NOT NULL,"
        " source_fit_id uuid NOT NULL,"
        " assessment_id uuid NOT NULL,"
        " score integer NOT NULL,"
        " requirements jsonb NOT NULL,"
        " requirement_map jsonb NOT NULL,"
        " target_profile jsonb NOT NULL,"
        " gaps jsonb NOT NULL,"
        " uncovered jsonb NOT NULL,"
        " created_at timestamptz NOT NULL DEFAULT now(),"
        " CONSTRAINT pk_posting_fit PRIMARY KEY (id),"
        " CONSTRAINT ck_posting_fit_basis CHECK (basis IN ('own'))"
        ")"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_posting_fit_owner_key"
        f" ON {_POSTING_FIT} (owner_id, posting_key, created_at)"
    )
    for table in _NEW:
        name = table.split(".")[1]
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_{name}_owner_id ON {table} (owner_id)")
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO app_rw")
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS owner_isolation ON {table}")
        op.execute(
            f"CREATE POLICY owner_isolation ON {table} FOR ALL "
            f"USING (owner_id::text = current_setting('{_APP_USER}', true)) "
            f"WITH CHECK (owner_id::text = current_setting('{_APP_USER}', true))"
        )


def _lift_force(tables: tuple[str, ...]) -> None:
    for table in tables:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")


def _restore_force(tables: tuple[str, ...]) -> None:
    for table in tables:
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
