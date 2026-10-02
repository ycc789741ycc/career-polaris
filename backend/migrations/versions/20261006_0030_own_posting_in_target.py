"""A posting of the user's own is Target's (ADR 0033).

A new ``target`` schema, owner zone, under RLS, with no grant to the crawler:

* ``target.private_job_posting``: the JD the user brought, moved from
  ``market_user.private_job_posting``, keeping its id, so every plan, résumé
  and question set aimed at it still names it.
* ``target.posting_evaluation``, ``target.posting_requirement`` and
  ``target.posting_requirement_fit``: the runs that read and score it, its
  requirements and the AI's evaluation of them, moved from ``rolemap``.
* ``target.own_posting_fit``: the fit worked out from that, moved from the
  ``basis = 'own'`` rows of ``rolemap.posting_fit``.

``rolemap.posting_fit`` then holds openings' fits only: it loses ``basis`` and
its checks, and ``role_id`` becomes NOT NULL. The old tables are dropped.

FORCE ROW LEVEL SECURITY holds even the owning migrator to the per-user policy,
so it is lifted on the tables read and written here, and restored after.

Written to be idempotent, since the baseline migration builds tables from the
live ORM metadata: on a fresh database the ``target`` tables already exist,
``market_user.private_job_posting`` never did, and ``rolemap.posting_fit`` has
no ``basis``. Migrations 0015, 0025 and 0028 were guarded for that.

Downgrading moves everything back, with ``basis = 'own'`` and the
``private:<id>`` key, and drops the schema. A JD moved back gets a canonical
key from its company and title alone and no embedding: neither was read once
it was a posting of the user's own.
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

from kernel.embeddings import EMBEDDING_DIMENSIONS

revision: str = "0030_own_posting_in_target"
down_revision: str | None = "0029_clean_role_names"
branch_labels = None
depends_on = None

_APP_USER = "app.user_id"
_POSTING = "target.private_job_posting"
_EVALUATION = "target.posting_evaluation"
_REQUIREMENT = "target.posting_requirement"
_REQUIREMENT_FIT = "target.posting_requirement_fit"
_FIT = "target.own_posting_fit"
_NEW = (_POSTING, _EVALUATION, _REQUIREMENT, _REQUIREMENT_FIT, _FIT)

_OLD_POSTING = "market_user.private_job_posting"
_OLD_EVALUATION = "rolemap.posting_evaluation"
_OLD_REQUIREMENT = "rolemap.posting_requirement"
_OLD_REQUIREMENT_FIT = "rolemap.posting_requirement_fit"
_OLD_FIT = "rolemap.posting_fit"
_OLD = (_OLD_POSTING, _OLD_EVALUATION, _OLD_REQUIREMENT, _OLD_REQUIREMENT_FIT, _OLD_FIT)


def upgrade() -> None:
    op.execute('CREATE SCHEMA IF NOT EXISTS "target"')
    op.execute('GRANT USAGE ON SCHEMA "target" TO app_rw')
    _create_tables()
    op.execute('GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA "target" TO app_rw')
    op.execute(
        'ALTER DEFAULT PRIVILEGES IN SCHEMA "target" '
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_rw"
    )
    for table in _NEW:
        _owner_isolation(table)

    old = tuple(table for table in _OLD if _exists(table))
    _lift_force((*_NEW, *old))
    if _exists(_OLD_POSTING):
        _copy_forward()
    _restore_force(_NEW)

    for table in (_OLD_EVALUATION, _OLD_REQUIREMENT, _OLD_REQUIREMENT_FIT, _OLD_POSTING):
        op.execute(f"DROP TABLE IF EXISTS {table}")
    if _has_column(_OLD_FIT, "basis"):
        op.execute(f"DELETE FROM {_OLD_FIT} WHERE basis = 'own'")  # noqa: S608
    op.execute(f"ALTER TABLE {_OLD_FIT} FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {_OLD_FIT} DROP CONSTRAINT IF EXISTS ck_posting_fit_role")
    op.execute(f"ALTER TABLE {_OLD_FIT} DROP CONSTRAINT IF EXISTS ck_posting_fit_basis")
    op.execute(f"ALTER TABLE {_OLD_FIT} DROP COLUMN IF EXISTS basis")
    op.execute(f"ALTER TABLE {_OLD_FIT} ALTER COLUMN role_id SET NOT NULL")


def _copy_forward() -> None:
    """Every pasted JD is a posting of the user's own since migration 0025, so
    all of them move, each with what was made of it. A second run inserts
    nothing twice."""
    op.execute(
        f"INSERT INTO {_POSTING}"  # noqa: S608
        " (id, owner_id, title, company_name, job_description, created_at)"
        " SELECT id, owner_id, title, nullif(btrim(company_name), ''), description, created_at"
        f" FROM {_OLD_POSTING}"
        " ON CONFLICT (id) DO NOTHING"
    )
    op.execute(
        f"INSERT INTO {_EVALUATION}"  # noqa: S608
        " (id, owner_id, private_job_posting_id, status, reads_requirements, error_code,"
        "  error_message, requested_at, finished_at)"
        " SELECT e.id, e.owner_id, e.private_job_posting_id, e.status, e.reads_requirements,"
        "  e.error_code, e.error_message, e.requested_at, e.finished_at"
        f" FROM {_OLD_EVALUATION} AS e JOIN {_POSTING} AS p ON p.id = e.private_job_posting_id"
        " ON CONFLICT (id) DO NOTHING"
    )
    op.execute(
        f"INSERT INTO {_REQUIREMENT}"  # noqa: S608
        " (id, owner_id, private_job_posting_id, statement, weight, expected_level)"
        " SELECT r.id, r.owner_id, r.private_job_posting_id, r.statement, r.weight,"
        "  r.expected_level"
        f" FROM {_OLD_REQUIREMENT} AS r JOIN {_POSTING} AS p ON p.id = r.private_job_posting_id"
        " ON CONFLICT (id) DO NOTHING"
    )
    op.execute(
        f"INSERT INTO {_REQUIREMENT_FIT}"  # noqa: S608
        " (id, owner_id, private_job_posting_id, assessment_id, requirements, requirement_map,"
        "  target_profile, reasoning, model_id, template_version, requirements_digest,"
        "  created_at)"
        " SELECT f.id, f.owner_id, f.private_job_posting_id, f.assessment_id, f.requirements,"
        "  f.requirement_map, f.target_profile, f.reasoning, f.model_id, f.template_version,"
        "  f.requirements_digest, f.created_at"
        f" FROM {_OLD_REQUIREMENT_FIT} AS f JOIN {_POSTING} AS p"
        "  ON p.id = f.private_job_posting_id"
        " ON CONFLICT (id) DO NOTHING"
    )
    op.execute(
        f"INSERT INTO {_FIT}"  # noqa: S608
        " (id, owner_id, private_job_posting_id, source_fit_id, assessment_id, score,"
        "  requirements, requirement_map, target_profile, gaps, uncovered, created_at)"
        " SELECT o.id, o.owner_id, p.id, o.source_fit_id, o.assessment_id, o.score,"
        "  o.requirements, o.requirement_map, o.target_profile, o.gaps, o.uncovered,"
        "  o.created_at"
        f" FROM {_OLD_FIT} AS o"
        f" JOIN {_POSTING} AS p ON o.posting_key = 'private:' || p.id::text"
        f" JOIN {_REQUIREMENT_FIT} AS s ON s.id = o.source_fit_id"
        " WHERE o.basis = 'own'"
        " ON CONFLICT (id) DO NOTHING"
    )


def downgrade() -> None:
    op.execute(
        f"CREATE TABLE IF NOT EXISTS {_OLD_POSTING} ("
        " id uuid NOT NULL,"
        " owner_id uuid NOT NULL,"
        " canonical_key varchar(768) NOT NULL,"
        " company_name varchar(255) NOT NULL,"
        " title varchar(512) NOT NULL,"
        " location varchar(255),"
        " description text NOT NULL,"
        " url varchar(1024),"
        " shared_posting_id uuid,"
        f" vector vector({EMBEDDING_DIMENSIONS}),"
        " created_at timestamptz NOT NULL DEFAULT now(),"
        " updated_at timestamptz NOT NULL DEFAULT now(),"
        " CONSTRAINT pk_private_job_posting PRIMARY KEY (id)"
        ")"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_private_job_posting_canonical_key"
        f" ON {_OLD_POSTING} (canonical_key)"
    )
    op.execute(
        f"CREATE TABLE IF NOT EXISTS {_OLD_EVALUATION} ("
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
        f" ON {_OLD_EVALUATION} (owner_id, private_job_posting_id, requested_at)"
    )
    op.execute(
        f"CREATE TABLE IF NOT EXISTS {_OLD_REQUIREMENT} ("
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
        f" ON {_OLD_REQUIREMENT} (private_job_posting_id)"
    )
    op.execute(
        f"CREATE TABLE IF NOT EXISTS {_OLD_REQUIREMENT_FIT} ("
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
        " requirements_digest varchar(64),"
        " created_at timestamptz NOT NULL DEFAULT now(),"
        " CONSTRAINT pk_posting_requirement_fit PRIMARY KEY (id)"
        ")"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_posting_requirement_fit_owner_posting"
        f" ON {_OLD_REQUIREMENT_FIT} (owner_id, private_job_posting_id, created_at)"
    )
    for table in _OLD[:4]:
        name = table.split(".")[1]
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_{name}_owner_id ON {table} (owner_id)")
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO app_rw")
        _owner_isolation(table)

    op.execute(f"ALTER TABLE {_OLD_FIT} ADD COLUMN IF NOT EXISTS basis varchar(8)")
    op.execute(f"ALTER TABLE {_OLD_FIT} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"UPDATE {_OLD_FIT} SET basis = 'role' WHERE basis IS NULL")  # noqa: S608
    op.execute(f"ALTER TABLE {_OLD_FIT} ALTER COLUMN basis SET NOT NULL")
    op.execute(f"ALTER TABLE {_OLD_FIT} ALTER COLUMN role_id DROP NOT NULL")
    op.execute(f"ALTER TABLE {_OLD_FIT} DROP CONSTRAINT IF EXISTS ck_posting_fit_basis")
    op.execute(
        f"ALTER TABLE {_OLD_FIT} ADD CONSTRAINT ck_posting_fit_basis"
        " CHECK (basis IN ('own', 'role'))"
    )
    op.execute(f"ALTER TABLE {_OLD_FIT} DROP CONSTRAINT IF EXISTS ck_posting_fit_role")
    op.execute(
        f"ALTER TABLE {_OLD_FIT} ADD CONSTRAINT ck_posting_fit_role"
        " CHECK ((basis = 'role') = (role_id IS NOT NULL))"
    )

    _lift_force(_OLD)
    if _exists(_POSTING):
        _lift_force(_NEW)
        _copy_back()
    _restore_force(_OLD)
    for table in reversed(_NEW):
        op.execute(f"DROP TABLE IF EXISTS {table}")
    op.execute('DROP SCHEMA IF EXISTS "target"')


def _copy_back() -> None:
    op.execute(
        f"INSERT INTO {_OLD_POSTING}"  # noqa: S608
        " (id, owner_id, canonical_key, company_name, title, location, description,"
        "  created_at, updated_at)"
        " SELECT id, owner_id,"
        "  left(lower(coalesce(company_name, '')) || '|' || lower(title) || '|unspecified', 768),"
        "  coalesce(company_name, ''), title, NULL, job_description, created_at, created_at"
        f" FROM {_POSTING}"
        " ON CONFLICT (id) DO NOTHING"
    )
    op.execute(
        f"INSERT INTO {_OLD_EVALUATION}"  # noqa: S608
        " (id, owner_id, private_job_posting_id, status, reads_requirements, error_code,"
        "  error_message, requested_at, finished_at)"
        " SELECT id, owner_id, private_job_posting_id, status, reads_requirements, error_code,"
        "  error_message, requested_at, finished_at"
        f" FROM {_EVALUATION}"
        " ON CONFLICT (id) DO NOTHING"
    )
    op.execute(
        f"INSERT INTO {_OLD_REQUIREMENT}"  # noqa: S608
        " (id, owner_id, private_job_posting_id, statement, weight, expected_level)"
        " SELECT id, owner_id, private_job_posting_id, statement, weight, expected_level"
        f" FROM {_REQUIREMENT}"
        " ON CONFLICT (id) DO NOTHING"
    )
    op.execute(
        f"INSERT INTO {_OLD_REQUIREMENT_FIT}"  # noqa: S608
        " (id, owner_id, private_job_posting_id, assessment_id, requirements, requirement_map,"
        "  target_profile, reasoning, model_id, template_version, requirements_digest,"
        "  created_at)"
        " SELECT id, owner_id, private_job_posting_id, assessment_id, requirements,"
        "  requirement_map, target_profile, reasoning, model_id, template_version,"
        "  requirements_digest, created_at"
        f" FROM {_REQUIREMENT_FIT}"
        " ON CONFLICT (id) DO NOTHING"
    )
    op.execute(
        f"INSERT INTO {_OLD_FIT}"  # noqa: S608
        " (id, owner_id, posting_key, basis, source_fit_id, assessment_id, score,"
        "  requirements, requirement_map, target_profile, gaps, uncovered, created_at)"
        " SELECT id, owner_id, 'private:' || private_job_posting_id::text, 'own', source_fit_id,"
        "  assessment_id, score, requirements, requirement_map, target_profile, gaps,"
        "  uncovered, created_at"
        f" FROM {_FIT}"
        " ON CONFLICT (id) DO NOTHING"
    )


def _create_tables() -> None:
    op.execute(
        f"CREATE TABLE IF NOT EXISTS {_POSTING} ("
        " id uuid NOT NULL,"
        " owner_id uuid NOT NULL,"
        " title varchar(512) NOT NULL,"
        " company_name varchar(255),"
        " job_description text NOT NULL,"
        " created_at timestamptz NOT NULL DEFAULT now(),"
        " CONSTRAINT pk_private_job_posting PRIMARY KEY (id)"
        ")"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_private_job_posting_owner_created"
        f" ON {_POSTING} (owner_id, created_at)"
    )
    posting_fk = f"REFERENCES {_POSTING} (id) ON DELETE CASCADE"
    op.execute(
        f"CREATE TABLE IF NOT EXISTS {_EVALUATION} ("
        " id uuid NOT NULL,"
        " owner_id uuid NOT NULL,"
        " private_job_posting_id uuid NOT NULL"
        f"  {posting_fk},"
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
        " private_job_posting_id uuid NOT NULL"
        f"  {posting_fk},"
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
        " private_job_posting_id uuid NOT NULL"
        f"  {posting_fk},"
        " assessment_id uuid NOT NULL,"
        " requirements jsonb NOT NULL,"
        " requirement_map jsonb NOT NULL,"
        " target_profile jsonb NOT NULL,"
        " reasoning text NOT NULL,"
        " model_id varchar(128) NOT NULL,"
        " template_version varchar(128) NOT NULL,"
        " requirements_digest varchar(64),"
        " created_at timestamptz NOT NULL DEFAULT now(),"
        " CONSTRAINT pk_posting_requirement_fit PRIMARY KEY (id)"
        ")"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_posting_requirement_fit_owner_posting"
        f" ON {_REQUIREMENT_FIT} (owner_id, private_job_posting_id, created_at)"
    )
    op.execute(
        f"CREATE TABLE IF NOT EXISTS {_FIT} ("
        " id uuid NOT NULL,"
        " owner_id uuid NOT NULL,"
        " private_job_posting_id uuid NOT NULL"
        f"  {posting_fk},"
        " source_fit_id uuid NOT NULL"
        f"  REFERENCES {_REQUIREMENT_FIT} (id) ON DELETE CASCADE,"
        " assessment_id uuid NOT NULL,"
        " score integer NOT NULL,"
        " requirements jsonb NOT NULL,"
        " requirement_map jsonb NOT NULL,"
        " target_profile jsonb NOT NULL,"
        " gaps jsonb NOT NULL,"
        " uncovered jsonb NOT NULL,"
        " created_at timestamptz NOT NULL DEFAULT now(),"
        " CONSTRAINT pk_own_posting_fit PRIMARY KEY (id)"
        ")"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_own_posting_fit_owner_posting"
        f" ON {_FIT} (owner_id, private_job_posting_id, created_at)"
    )
    for table in _NEW:
        name = table.split(".")[1]
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_{name}_owner_id ON {table} (owner_id)")


def _owner_isolation(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS owner_isolation ON {table}")
    op.execute(
        f"CREATE POLICY owner_isolation ON {table} FOR ALL "
        f"USING (owner_id::text = current_setting('{_APP_USER}', true)) "
        f"WITH CHECK (owner_id::text = current_setting('{_APP_USER}', true))"
    )


def _exists(table: str) -> bool:
    found = op.get_bind().execute(text("SELECT to_regclass(:table)"), {"table": table}).scalar()
    return found is not None


def _has_column(table: str, column: str) -> bool:
    schema, _, name = table.partition(".")
    found = (
        op.get_bind()
        .execute(
            text(
                "SELECT 1 FROM information_schema.columns"
                " WHERE table_schema = :schema AND table_name = :name AND column_name = :column"
            ),
            {"schema": schema, "name": name, "column": column},
        )
        .scalar()
    )
    return found is not None


def _lift_force(tables: tuple[str, ...]) -> None:
    for table in tables:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")


def _restore_force(tables: tuple[str, ...]) -> None:
    for table in tables:
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
