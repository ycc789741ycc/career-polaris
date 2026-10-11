"""A résumé may size its name, its entries' titles and its headings (ADR 0078).

``resume.resume`` gains ``name_pt``, ``title_pt`` and ``heading_pt``, all
nullable, null keeping the template's, each checked to the range a template's
may take, as the ranges stood when this was written. Nothing stored changes
how it prints.

Idempotent, since the baseline migration builds tables from the live ORM
metadata. Downgrading drops the three columns and their checks.
"""

from __future__ import annotations

from alembic import op

revision: str = "0059_resume_own_sizes"
down_revision: str | None = "0058_answers_read_into_the_fit"
branch_labels = None
depends_on = None

_COLUMNS = (
    ("name_pt", 16.0, 30.0),
    ("title_pt", 9.0, 14.0),
    ("heading_pt", 7.0, 11.0),
)


def upgrade() -> None:
    for column, low, high in _COLUMNS:
        op.execute(f"ALTER TABLE resume.resume ADD COLUMN IF NOT EXISTS {column} double precision")
        op.execute(f"ALTER TABLE resume.resume DROP CONSTRAINT IF EXISTS ck_resume_{column}")
        op.execute(
            f"ALTER TABLE resume.resume ADD CONSTRAINT ck_resume_{column}"
            f" CHECK ({column} IS NULL OR {column} BETWEEN {low} AND {high})"
        )


def downgrade() -> None:
    for column, _low, _high in _COLUMNS:
        op.execute(f"ALTER TABLE resume.resume DROP CONSTRAINT IF EXISTS ck_resume_{column}")
        op.execute(f"ALTER TABLE resume.resume DROP COLUMN IF EXISTS {column}")
