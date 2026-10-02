"""A fit records what it read (Phase 8).

Owner zone, under RLS: ``rolemap.role_fit`` and
``rolemap.posting_requirement_fit`` gain ``requirements_digest``, a hash of the
requirements scored and the fit prompt's version. With ``assessment_id`` it
says whether scoring again would change anything, so ``compute_fits`` and a
rescore skip a fit that would come out the same.

Existing fits get no digest, so each is scored once more, by the next build
or rescore, and carries one from then on. Nothing is backfilled: the hash
covers the prompt version, which the stored fits were not hashed with.

Idempotent, since the baseline migration builds tables from the live ORM
metadata. Downgrading drops the columns.
"""

from __future__ import annotations

from alembic import op

revision: str = "0027_fit_requirements_digest"
down_revision: str | None = "0026_candidate_placement"
branch_labels = None
depends_on = None

_TABLES = ("rolemap.role_fit", "rolemap.posting_requirement_fit")


def upgrade() -> None:
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS requirements_digest varchar(64)")


def downgrade() -> None:
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS requirements_digest")
