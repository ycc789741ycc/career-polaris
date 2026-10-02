"""A role candidate is only a query; a build records what it made of each
(Phase 8, ADR 0031).

Owner zone, under RLS:

* ``rolemap.candidate_placement``: one row per candidate a build read, with
  its outcome (``placed``, ``outside_top_k`` or ``too_few_openings``), the
  role it became, its opening count and its fit estimate. The candidate's rank
  and title are copied in.
* Each current candidate's outcome moves there, against its owner's latest
  ``ready`` build: placed when it has a role; otherwise ``too_few_openings``
  when it had fewer than three openings (``MIN_POSTINGS_FOR_A_ROLE``), and
  ``outside_top_k`` when it had enough. An owner with no finished build has
  nothing to move: their candidates read as not built yet.
* ``rolemap.role_candidate`` loses ``role_id``, ``opening_count`` and
  ``fit_estimate``.

FORCE ROW LEVEL SECURITY holds even the owning migrator to the per-user policy,
so it is lifted on the tables read and written here, and restored after.

Written to be idempotent, since the baseline migration builds tables from the
live ORM metadata: on a fresh database the table exists already, and
``rolemap.role_candidate`` never had the three columns.

Downgrading gives the candidates their columns back from their latest
placement, and drops the table.
"""

from __future__ import annotations

from alembic import op

revision: str = "0026_candidate_placement"
down_revision: str | None = "0025_own_posting_target"
branch_labels = None
depends_on = None

_APP_USER = "app.user_id"
_PLACEMENT = "rolemap.candidate_placement"
_CANDIDATE = "rolemap.role_candidate"
_TABLES = (_PLACEMENT, _CANDIDATE, "rolemap.build_run")

# Each current candidate's outcome, against its owner's latest ready build.
_MOVE = (
    "INSERT INTO rolemap.candidate_placement"
    " (id, owner_id, build_run_id, candidate_id, rank, title, outcome, role_id,"
    "  opening_count, fit_estimate, created_at)"
    " SELECT gen_random_uuid(), c.owner_id, b.id, c.id, c.rank, c.title,"
    "  CASE WHEN c.role_id IS NOT NULL THEN 'placed'"
    "   WHEN c.opening_count >= 3 THEN 'outside_top_k'"
    "   ELSE 'too_few_openings' END,"
    "  c.role_id, c.opening_count, c.fit_estimate, coalesce(b.finished_at, now())"
    " FROM rolemap.role_candidate AS c"
    " JOIN LATERAL (SELECT id, finished_at FROM rolemap.build_run AS r"
    "  WHERE r.owner_id = c.owner_id AND r.status = 'ready'"
    "  ORDER BY r.requested_at DESC LIMIT 1) AS b ON true"
    " ON CONFLICT ON CONSTRAINT uq_candidate_placement_build_run_id DO NOTHING; "
)


def upgrade() -> None:
    op.execute(
        f"CREATE TABLE IF NOT EXISTS {_PLACEMENT} ("
        " id uuid NOT NULL,"
        " owner_id uuid NOT NULL,"
        " build_run_id uuid NOT NULL,"
        " candidate_id uuid,"
        " rank integer NOT NULL,"
        " title varchar(255) NOT NULL,"
        " outcome varchar(24) NOT NULL,"
        " role_id uuid,"
        " opening_count integer NOT NULL,"
        " fit_estimate double precision,"
        " created_at timestamptz NOT NULL DEFAULT now(),"
        " CONSTRAINT pk_candidate_placement PRIMARY KEY (id),"
        " CONSTRAINT uq_candidate_placement_build_run_id UNIQUE (build_run_id, candidate_id),"
        " CONSTRAINT ck_candidate_placement_outcome"
        "  CHECK (outcome IN ('placed', 'outside_top_k', 'too_few_openings')),"
        " CONSTRAINT ck_candidate_placement_role"
        "  CHECK ((outcome = 'placed') = (role_id IS NOT NULL)),"
        " CONSTRAINT fk_candidate_placement_build_run_id_build_run"
        "  FOREIGN KEY (build_run_id) REFERENCES rolemap.build_run (id) ON DELETE CASCADE,"
        " CONSTRAINT fk_candidate_placement_candidate_id_role_candidate"
        "  FOREIGN KEY (candidate_id) REFERENCES rolemap.role_candidate (id) ON DELETE SET NULL,"
        " CONSTRAINT fk_candidate_placement_role_id_role"
        "  FOREIGN KEY (role_id) REFERENCES rolemap.role (id) ON DELETE SET NULL"
        ")"
    )
    for column in ("owner_id", "build_run_id", "candidate_id"):
        op.execute(
            f"CREATE INDEX IF NOT EXISTS ix_candidate_placement_{column} ON {_PLACEMENT} ({column})"
        )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {_PLACEMENT} TO app_rw")
    op.execute(f"ALTER TABLE {_PLACEMENT} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {_PLACEMENT} FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS owner_isolation ON {_PLACEMENT}")
    op.execute(
        f"CREATE POLICY owner_isolation ON {_PLACEMENT} FOR ALL "
        f"USING (owner_id::text = current_setting('{_APP_USER}', true)) "
        f"WITH CHECK (owner_id::text = current_setting('{_APP_USER}', true))"
    )

    _lift_force(_TABLES)
    op.execute(
        "DO $$ BEGIN "  # noqa: S608
        "IF EXISTS (SELECT 1 FROM information_schema.columns"
        "  WHERE table_schema = 'rolemap' AND table_name = 'role_candidate'"
        "  AND column_name = 'role_id') THEN "
        f"{_MOVE}"
        "END IF; "
        "END $$"
    )
    _restore_force(_TABLES)

    for column in ("role_id", "opening_count", "fit_estimate"):
        op.execute(f"ALTER TABLE {_CANDIDATE} DROP COLUMN IF EXISTS {column}")


def downgrade() -> None:
    op.execute(
        f"ALTER TABLE {_CANDIDATE} ADD COLUMN IF NOT EXISTS role_id uuid"
        " REFERENCES rolemap.role (id) ON DELETE SET NULL"
    )
    op.execute(
        f"ALTER TABLE {_CANDIDATE} ADD COLUMN IF NOT EXISTS opening_count integer"
        " NOT NULL DEFAULT 0"
    )
    op.execute(f"ALTER TABLE {_CANDIDATE} ADD COLUMN IF NOT EXISTS fit_estimate double precision")
    _lift_force(_TABLES)
    op.execute(
        "UPDATE rolemap.role_candidate AS c"
        " SET role_id = p.role_id, opening_count = p.opening_count,"
        "  fit_estimate = p.fit_estimate"
        " FROM (SELECT DISTINCT ON (candidate_id) candidate_id, role_id, opening_count,"
        "  fit_estimate FROM rolemap.candidate_placement WHERE candidate_id IS NOT NULL"
        "  ORDER BY candidate_id, created_at DESC) AS p"
        " WHERE p.candidate_id = c.id"
    )
    _restore_force(_TABLES)
    op.execute(f"DROP TABLE IF EXISTS {_PLACEMENT}")


def _lift_force(tables: tuple[str, ...]) -> None:
    for table in tables:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")


def _restore_force(tables: tuple[str, ...]) -> None:
    for table in tables:
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
