"""A résumé may set its own fonts over its template's (ADR 0047).

``resume.resume`` gains ``heading_font`` and ``body_font``, both nullable:
null keeps the template's. Each is checked to be one of the fonts a résumé
can set, as the list stood when this was written.

Idempotent, since the baseline migration builds tables from the live ORM
metadata. Downgrading drops both columns and their checks.
"""

from __future__ import annotations

from alembic import op

revision: str = "0041_resume_fonts"
down_revision: str | None = "0040_career_timeline_reading"
branch_labels = None
depends_on = None

_FONTS = "'Caprasimo', 'Figtree', 'DejaVu Serif', 'DejaVu Sans Mono'"


def upgrade() -> None:
    for column in ("heading_font", "body_font"):
        op.execute(f"ALTER TABLE resume.resume ADD COLUMN IF NOT EXISTS {column} varchar(32)")
        op.execute(f"ALTER TABLE resume.resume DROP CONSTRAINT IF EXISTS ck_resume_{column}")
        op.execute(
            f"ALTER TABLE resume.resume ADD CONSTRAINT ck_resume_{column}"
            f" CHECK ({column} IS NULL OR {column} IN ({_FONTS}))"
        )


def downgrade() -> None:
    for column in ("heading_font", "body_font"):
        op.execute(f"ALTER TABLE resume.resume DROP CONSTRAINT IF EXISTS ck_resume_{column}")
        op.execute(f"ALTER TABLE resume.resume DROP COLUMN IF EXISTS {column}")
