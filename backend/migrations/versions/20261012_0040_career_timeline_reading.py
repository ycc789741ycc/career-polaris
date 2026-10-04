"""The career timeline is the analysis's reading of the evidence (ADR 0045).

``profile.position`` gains ``evidence_ids``, the résumé lines and answers a
position was read from, and ``skill_assessment_id``, the analysis that read
it. No row was ever written to the table before this, so there is nothing to
backfill.

Idempotent, since the baseline migration builds tables from the live ORM
metadata. Downgrading drops both columns.
"""

from __future__ import annotations

from alembic import op

revision: str = "0040_career_timeline_reading"
down_revision: str | None = "0039_resume_all_sections"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE profile.position"
        " ADD COLUMN IF NOT EXISTS evidence_ids jsonb NOT NULL DEFAULT '[]'::jsonb"
    )
    op.execute("ALTER TABLE profile.position ADD COLUMN IF NOT EXISTS skill_assessment_id uuid")


def downgrade() -> None:
    op.execute("ALTER TABLE profile.position DROP COLUMN IF EXISTS skill_assessment_id")
    op.execute("ALTER TABLE profile.position DROP COLUMN IF EXISTS evidence_ids")
