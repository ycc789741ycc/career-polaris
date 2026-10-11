"""A build records the analysis it built from (ADR 0071).

No build follows an analysis any more, so the role map says when the
strengths changed since it was built. ``rolemap.build_run`` gains
``skill_assessment_id``: the analysis whose candidates the build placed.

Finished builds are backfilled from their placements: a placement's candidate,
while it still exists, names the analysis that recommended it. A build whose
candidates were since replaced keeps a null, and reads as current.

FORCE ROW LEVEL SECURITY holds even the owning migrator to the per-user policy,
so it is lifted while every owner's rows are read and written, and restored
after (as migration 0030 does). Idempotent: a build given its analysis once is
skipped. Downgrading drops the column.
"""

from __future__ import annotations

from alembic import op

revision: str = "0054_build_skill_assessment"
down_revision: str | None = "0053_platform_by_default"
branch_labels = None
depends_on = None

_TABLES = ("rolemap.build_run", "rolemap.candidate_placement", "rolemap.role_candidate")

# Written to hold under a per-user policy too, so a test can run it as one owner.
BACKFILL_SKILL_ASSESSMENTS = (
    "UPDATE rolemap.build_run AS build"
    " SET skill_assessment_id = placed.assessment_id"
    " FROM (SELECT DISTINCT ON (placement.build_run_id)"
    "  placement.build_run_id, candidate.assessment_id"
    "  FROM rolemap.candidate_placement AS placement"
    "  JOIN rolemap.role_candidate AS candidate ON candidate.id = placement.candidate_id"
    "  ORDER BY placement.build_run_id, placement.rank) AS placed"
    " WHERE placed.build_run_id = build.id"
    " AND build.status = 'ready'"
    " AND build.skill_assessment_id IS NULL"
)


def upgrade() -> None:
    op.execute("ALTER TABLE rolemap.build_run ADD COLUMN IF NOT EXISTS skill_assessment_id uuid")
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    op.execute(BACKFILL_SKILL_ASSESSMENTS)
    for table in reversed(_TABLES):
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("ALTER TABLE rolemap.build_run DROP COLUMN IF EXISTS skill_assessment_id")
