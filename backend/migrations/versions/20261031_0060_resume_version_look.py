"""Each résumé version keeps the look it was saved in (ADR 0079).

``resume.version`` gains ``look``, a JSONB copy of ``VersionLook.to_dict()``:
the template (built in, or the id of one of the user's own), the résumé's own
fonts, bold switches and sizes, and the trim. Every version stored before this
takes its résumé's look as it is now, the best record there is, so each prints
as it did the moment before. Then the column is NOT NULL.

Both tables force row-level security, which binds even the migrator, their
owner: with no ``app.user_id`` the backfill would see no rows. It lifts the
force for its two statements and puts it back, as migration 0042 does.

Idempotent, since the baseline migration builds tables from the live ORM
metadata. Downgrading drops the column.
"""

from __future__ import annotations

from collections.abc import Callable

from alembic import op

revision: str = "0060_resume_version_look"
down_revision: str | None = "0059_resume_own_sizes"
branch_labels = None
depends_on = None


# A résumé's look as ``VersionLook.to_dict()`` keeps it, read from ``r``.
LOOK_OF_RESUME = """
    jsonb_build_object(
        'template', r.template,
        'custom_template_id', r.custom_template_id::text,
        'heading_font', r.heading_font,
        'section_font', r.section_font,
        'body_font', r.body_font,
        'bold_titles', r.bold_titles,
        'bold_headings', r.bold_headings,
        'body_pt', r.body_pt,
        'name_pt', r.name_pt,
        'title_pt', r.title_pt,
        'heading_pt', r.heading_pt,
        'trim', COALESCE((r.options->>'trim')::boolean, false)
    )
"""


_TABLES = ("resume.resume", "resume.version")


def backfill(execute: Callable[[str], object]) -> None:
    """Give every version with no look its résumé's, seeing every owner's."""
    for table in _TABLES:
        execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    # The expression is this module's own constant, never input.
    execute(
        f"UPDATE resume.version AS v SET look = {LOOK_OF_RESUME}"  # noqa: S608
        " FROM resume.resume AS r WHERE r.id = v.resume_id AND v.look IS NULL"
    )
    for table in _TABLES:
        execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    op.execute("ALTER TABLE resume.version ADD COLUMN IF NOT EXISTS look jsonb")
    backfill(op.execute)
    op.execute("ALTER TABLE resume.version ALTER COLUMN look SET NOT NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE resume.version DROP COLUMN IF EXISTS look")
