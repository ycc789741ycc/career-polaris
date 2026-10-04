"""More fonts a résumé can set: Inter, Lato, Source Serif 4, Merriweather,
EB Garamond and IBM Plex Mono, bundled in the worker image beside the four
there were (ADR 0047).

``resume.resume``'s ``heading_font`` and ``body_font`` checks are widened to
the list as it stands now. A template of one's own keeps its fonts in its
spec, checked by the domain, so nothing else changes. Downgrading narrows the
checks back, after setting any résumé that named a new font back to its
template's.
"""

from __future__ import annotations

from alembic import op

revision: str = "0043_more_resume_fonts"
down_revision: str | None = "0042_resume_contacts"
branch_labels = None
depends_on = None

_BEFORE = ("Caprasimo", "Figtree", "DejaVu Serif", "DejaVu Sans Mono")
_ADDED = ("Inter", "Lato", "Source Serif 4", "Merriweather", "EB Garamond", "IBM Plex Mono")


def _check(fonts: tuple[str, ...]) -> None:
    listed = ", ".join(f"'{font}'" for font in fonts)
    for column in ("heading_font", "body_font"):
        op.execute(f"ALTER TABLE resume.resume DROP CONSTRAINT IF EXISTS ck_resume_{column}")
        op.execute(
            f"ALTER TABLE resume.resume ADD CONSTRAINT ck_resume_{column}"
            f" CHECK ({column} IS NULL OR {column} IN ({listed}))"
        )


def upgrade() -> None:
    _check(_BEFORE + _ADDED)


def downgrade() -> None:
    added = ", ".join(f"'{font}'" for font in _ADDED)
    for column in ("heading_font", "body_font"):
        op.execute(
            f"UPDATE resume.resume SET {column} = NULL WHERE {column} IN ({added})"  # noqa: S608 - fixed names
        )
    _check(_BEFORE)
