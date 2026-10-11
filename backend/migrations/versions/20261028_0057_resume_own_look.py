"""A résumé may set more of its own look over its template's (ADR 0075).

``resume.resume`` gains, all nullable, null keeping the template's:
``section_font`` (its section headings' font, one of the fonts a résumé can
set, as the list stood when this was written), ``bold_titles`` and
``bold_headings``, and ``body_pt`` (its text size, in the range a template's
may take). Nothing stored changes how it prints.

Idempotent, since the baseline migration builds tables from the live ORM
metadata. Downgrading drops the four columns and their checks.
"""

from __future__ import annotations

from alembic import op

revision: str = "0057_resume_own_look"
down_revision: str | None = "0056_opening_fit_in_target"
branch_labels = None
depends_on = None

_FONTS = ", ".join(
    f"'{font}'"
    for font in (
        "Caprasimo",
        "Figtree",
        "DejaVu Serif",
        "DejaVu Sans Mono",
        "Inter",
        "Lato",
        "Source Serif 4",
        "Merriweather",
        "EB Garamond",
        "IBM Plex Mono",
    )
)
_COLUMNS = (
    ("section_font", "varchar(32)", f"section_font IS NULL OR section_font IN ({_FONTS})"),
    ("bold_titles", "boolean", None),
    ("bold_headings", "boolean", None),
    ("body_pt", "double precision", "body_pt IS NULL OR body_pt BETWEEN 8.5 AND 11.5"),
)


def upgrade() -> None:
    for column, kind, check in _COLUMNS:
        op.execute(f"ALTER TABLE resume.resume ADD COLUMN IF NOT EXISTS {column} {kind}")
        if check is not None:
            op.execute(f"ALTER TABLE resume.resume DROP CONSTRAINT IF EXISTS ck_resume_{column}")
            op.execute(
                f"ALTER TABLE resume.resume ADD CONSTRAINT ck_resume_{column} CHECK ({check})"
            )


def downgrade() -> None:
    for column, _kind, check in _COLUMNS:
        if check is not None:
            op.execute(f"ALTER TABLE resume.resume DROP CONSTRAINT IF EXISTS ck_resume_{column}")
        op.execute(f"ALTER TABLE resume.resume DROP COLUMN IF EXISTS {column}")
