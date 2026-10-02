"""The fit moves from ``assessment`` into ``rolemap`` (ADR 0028).

Owner zone, under RLS:

* ``rolemap.role_fit``: every fit taken, as ``assessment.role_fit`` held them,
  less the pasted-posting column nothing has written since ADR 0022. Rows are
  copied over and ``assessment.role_fit`` is dropped.
* ``rolemap.candidate_strength`` gains each dimension's ``score`` and
  ``confidence``, which the fit is now scored against. Existing rows take them
  from the scores of the analysis that handed them over.
* A user whose latest analysis predates the hand-over (migration 0022) gets
  their strengths from it now, so their fits can still be scored without
  analysing again.

FORCE ROW LEVEL SECURITY holds even the owning migrator to the per-user policy,
so it is lifted on the tables read and written here, and restored after.

Written to be idempotent, since the baseline migration builds tables from the
live ORM metadata: on a fresh database ``rolemap.role_fit`` and the new columns
already exist, and ``assessment.role_fit`` never did.

Downgrading moves the fits back and drops the new columns.
"""

from __future__ import annotations

from alembic import op

revision: str = "0023_fits_in_rolemap"
down_revision: str | None = "0022_market_on_demand"
branch_labels = None
depends_on = None

_APP_USER = "app.user_id"
_FIT = "rolemap.role_fit"
_STRENGTH = "rolemap.candidate_strength"
_READ = (
    "assessment.skill_assessment",
    "assessment.dimension_score",
    "assessment.skill_dimension",
)


def upgrade() -> None:
    op.execute(
        f"CREATE TABLE IF NOT EXISTS {_FIT} ("
        " id uuid NOT NULL,"
        " owner_id uuid NOT NULL,"
        " assessment_id uuid NOT NULL,"
        " role_id uuid NOT NULL,"
        " score integer NOT NULL,"
        " reasoning text NOT NULL,"
        " target_profile jsonb NOT NULL,"
        " gaps jsonb NOT NULL,"
        " uncovered jsonb NOT NULL,"
        " requirements jsonb NOT NULL DEFAULT '[]'::jsonb,"
        " requirement_map jsonb NOT NULL DEFAULT '{}'::jsonb,"
        " model_id varchar(128) NOT NULL,"
        " template_version varchar(128) NOT NULL,"
        " created_at timestamptz NOT NULL DEFAULT now(),"
        " CONSTRAINT pk_role_fit PRIMARY KEY (id)"
        ")"
    )
    op.execute(f"CREATE INDEX IF NOT EXISTS ix_role_fit_owner_id ON {_FIT} (owner_id)")
    op.execute(
        f"CREATE INDEX IF NOT EXISTS ix_role_fit_owner_role ON {_FIT} "
        "(owner_id, role_id, created_at)"
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {_FIT} TO app_rw")
    op.execute(f"ALTER TABLE {_FIT} ENABLE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS owner_isolation ON {_FIT}")
    op.execute(
        f"CREATE POLICY owner_isolation ON {_FIT} FOR ALL "
        f"USING (owner_id::text = current_setting('{_APP_USER}', true)) "
        f"WITH CHECK (owner_id::text = current_setting('{_APP_USER}', true))"
    )

    op.execute(f"ALTER TABLE {_STRENGTH} ADD COLUMN IF NOT EXISTS score integer")
    op.execute(f"ALTER TABLE {_STRENGTH} ADD COLUMN IF NOT EXISTS confidence double precision")

    _lift_force((_FIT, _STRENGTH, *_READ))
    op.execute(
        "DO $$ BEGIN "
        "IF to_regclass('assessment.role_fit') IS NOT NULL THEN "
        "  ALTER TABLE assessment.role_fit NO FORCE ROW LEVEL SECURITY; "
        "  INSERT INTO rolemap.role_fit (id, owner_id, assessment_id, role_id, score,"
        "   reasoning, target_profile, gaps, uncovered, requirements, requirement_map,"
        "   model_id, template_version, created_at)"
        "  SELECT id, owner_id, assessment_id, role_id, score, reasoning, target_profile,"
        "   gaps, uncovered, requirements, requirement_map, model_id, template_version,"
        "   created_at"
        "  FROM assessment.role_fit WHERE role_id IS NOT NULL"
        "  ON CONFLICT (id) DO NOTHING; "
        "  DROP TABLE assessment.role_fit; "
        "END IF; "
        "END $$"
    )
    # A strength handed over before this has its score from the same analysis.
    op.execute(
        "UPDATE rolemap.candidate_strength AS s"
        " SET score = a.score, confidence = a.confidence"
        " FROM assessment.dimension_score AS a"
        " WHERE a.assessment_id = s.assessment_id AND a.dimension_key = s.dimension_key"
        " AND s.score IS NULL"
    )
    # None should be left; if one is, keep its weight rather than invent a score.
    op.execute(
        "UPDATE rolemap.candidate_strength"
        " SET score = round(weight * 100), confidence = 1.0"
        " WHERE score IS NULL OR confidence IS NULL"
    )
    # Users analysed before the hand-over existed: strengths from their latest.
    op.execute(
        "INSERT INTO rolemap.candidate_strength"
        " (id, owner_id, assessment_id, dimension_key, name, read, weight, score, confidence)"
        " SELECT gen_random_uuid(), a.owner_id, a.assessment_id, a.dimension_key,"
        "  coalesce(d.name, a.dimension_key), a.read, a.score / 100.0 * a.confidence,"
        "  a.score, a.confidence"
        " FROM assessment.dimension_score AS a"
        " JOIN (SELECT DISTINCT ON (owner_id) id, owner_id FROM assessment.skill_assessment"
        "       ORDER BY owner_id, created_at DESC) AS latest ON latest.id = a.assessment_id"
        " LEFT JOIN assessment.skill_dimension AS d"
        "  ON d.owner_id = a.owner_id AND d.key = a.dimension_key"
        " WHERE NOT EXISTS ("
        "  SELECT 1 FROM rolemap.candidate_strength AS s WHERE s.owner_id = a.owner_id)"
    )
    _restore_force((_FIT, _STRENGTH, *_READ))

    op.execute(f"ALTER TABLE {_STRENGTH} ALTER COLUMN score SET NOT NULL")
    op.execute(f"ALTER TABLE {_STRENGTH} ALTER COLUMN confidence SET NOT NULL")


def downgrade() -> None:
    op.execute(
        "CREATE TABLE IF NOT EXISTS assessment.role_fit ("
        " id uuid NOT NULL,"
        " owner_id uuid NOT NULL,"
        " assessment_id uuid NOT NULL,"
        " role_id uuid,"
        " private_posting_id uuid,"
        " score integer NOT NULL,"
        " reasoning text NOT NULL,"
        " target_profile jsonb NOT NULL,"
        " gaps jsonb NOT NULL,"
        " uncovered jsonb NOT NULL,"
        " requirements jsonb NOT NULL DEFAULT '[]'::jsonb,"
        " requirement_map jsonb NOT NULL DEFAULT '{}'::jsonb,"
        " model_id varchar(128) NOT NULL,"
        " template_version varchar(128) NOT NULL,"
        " created_at timestamptz NOT NULL DEFAULT now(),"
        " CONSTRAINT pk_role_fit PRIMARY KEY (id)"
        ")"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_role_fit_owner_target ON assessment.role_fit "
        "(owner_id, role_id, created_at)"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON assessment.role_fit TO app_rw")
    op.execute("ALTER TABLE assessment.role_fit ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS owner_isolation ON assessment.role_fit")
    op.execute(
        "CREATE POLICY owner_isolation ON assessment.role_fit FOR ALL "
        f"USING (owner_id::text = current_setting('{_APP_USER}', true)) "
        f"WITH CHECK (owner_id::text = current_setting('{_APP_USER}', true))"
    )
    _lift_force((_FIT, "assessment.role_fit"))
    op.execute(
        "INSERT INTO assessment.role_fit (id, owner_id, assessment_id, role_id, score,"
        " reasoning, target_profile, gaps, uncovered, requirements, requirement_map,"
        " model_id, template_version, created_at)"
        " SELECT id, owner_id, assessment_id, role_id, score, reasoning, target_profile,"
        " gaps, uncovered, requirements, requirement_map, model_id, template_version,"
        " created_at FROM rolemap.role_fit"
        " ON CONFLICT (id) DO NOTHING"
    )
    _restore_force(("assessment.role_fit",))
    op.execute(f"DROP TABLE IF EXISTS {_FIT}")
    op.execute(f"ALTER TABLE {_STRENGTH} DROP COLUMN IF EXISTS confidence")
    op.execute(f"ALTER TABLE {_STRENGTH} DROP COLUMN IF EXISTS score")


def _lift_force(tables: tuple[str, ...]) -> None:
    for table in tables:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")


def _restore_force(tables: tuple[str, ...]) -> None:
    for table in tables:
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
