"""A résumé is a header and an ordered list of sections (ADR 0039).

* ``resume.resume`` gains ``section_plan``, the sections every new version is
  written to, ``[{kind, title}]``; every résumé starts with summary,
  experience and skills, as they all were.
* Its ``status`` may be ``filling``: one section being filled from the sources.
* Every saved version's ``content``, and every chat revision's stored
  ``proposal``, moves from ``{summary, experience, skills}`` to ``sections``:
  a summary with its text, experience with one entry per position (and an
  empty link), and skills with their items, in that order. Nothing is lost.

Row-level security is lifted for the rewrite, as the rows are every user's.
Downgrading puts the three fields back from the summary, experience and
skills sections, so any other section is lost, sets ``filling`` back to
``ready``, and drops the column.
"""

from __future__ import annotations

from alembic import op

revision: str = "0035_resume_sections"
down_revision: str | None = "0034_export_trim"
branch_labels = None
depends_on = None

_DEFAULT_PLAN = (
    """'[{"kind": "summary", "title": null}, {"kind": "experience", "title": null},"""
    """ {"kind": "skills", "title": null}]'::jsonb"""
)


def _to_sections(column: str) -> str:
    """SQL that rewrites the old shape held in ``column`` into sections."""
    return f"""jsonb_build_object(
        'name', coalesce({column}->'name', '""'::jsonb),
        'headline', coalesce({column}->'headline', '""'::jsonb),
        'contact', coalesce({column}->'contact', '""'::jsonb),
        'sections', jsonb_build_array(
            jsonb_build_object(
                'kind', 'summary', 'title', null,
                'text', coalesce({column}->'summary', '""'::jsonb),
                'entries', '[]'::jsonb, 'items', '[]'::jsonb, 'bullets', '[]'::jsonb),
            jsonb_build_object(
                'kind', 'experience', 'title', null, 'text', '',
                'entries', coalesce((
                    SELECT jsonb_agg(
                        jsonb_build_object(
                            'title', coalesce(p->'title', '""'::jsonb),
                            'org', coalesce(p->'org', '""'::jsonb),
                            'when', coalesce(p->'when', '""'::jsonb),
                            'link', '',
                            'bullets', coalesce(p->'bullets', '[]'::jsonb))
                        ORDER BY n)
                    FROM jsonb_array_elements(coalesce({column}->'experience', '[]'::jsonb))
                        WITH ORDINALITY AS e(p, n)), '[]'::jsonb),
                'items', '[]'::jsonb, 'bullets', '[]'::jsonb),
            jsonb_build_object(
                'kind', 'skills', 'title', null, 'text', '', 'entries', '[]'::jsonb,
                'items', coalesce({column}->'skills', '[]'::jsonb), 'bullets', '[]'::jsonb)))"""  # noqa: S608 - a fixed column name


def _from_sections(column: str) -> str:
    """SQL that puts the three old fields back from ``column``'s sections."""
    return f"""jsonb_build_object(
        'name', coalesce({column}->'name', '""'::jsonb),
        'headline', coalesce({column}->'headline', '""'::jsonb),
        'contact', coalesce({column}->'contact', '""'::jsonb),
        'summary', coalesce((
            SELECT s->'text' FROM jsonb_array_elements({column}->'sections') AS x(s)
            WHERE s->>'kind' = 'summary' LIMIT 1), '""'::jsonb),
        'experience', coalesce((
            SELECT jsonb_agg(
                jsonb_build_object(
                    'title', p->'title', 'org', p->'org', 'when', p->'when',
                    'bullets', p->'bullets')
                ORDER BY n)
            FROM jsonb_array_elements({column}->'sections') AS x(s),
                 jsonb_array_elements(s->'entries') WITH ORDINALITY AS e(p, n)
            WHERE s->>'kind' = 'experience'), '[]'::jsonb),
        'skills', coalesce((
            SELECT s->'items' FROM jsonb_array_elements({column}->'sections') AS x(s)
            WHERE s->>'kind' = 'skills' LIMIT 1), '[]'::jsonb))"""  # noqa: S608 - a fixed column name


def _with_rls_lifted(tables: tuple[str, ...], statements: list[str]) -> None:
    for table in tables:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    for statement in statements:
        op.execute(statement)
    for table in tables:
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    op.execute(
        "ALTER TABLE resume.resume ADD COLUMN IF NOT EXISTS section_plan jsonb"
        f" NOT NULL DEFAULT {_DEFAULT_PLAN}"
    )
    op.execute("ALTER TABLE resume.resume DROP CONSTRAINT IF EXISTS ck_resume_status")
    op.execute(
        "ALTER TABLE resume.resume ADD CONSTRAINT ck_resume_status"
        " CHECK (status IN ('drafting', 'ready', 'failed', 'filling'))"
    )
    _with_rls_lifted(
        ("resume.version", "resume.revision"),
        [
            f"UPDATE resume.version SET content = {_to_sections('content')}"  # noqa: S608
            " WHERE NOT content ? 'sections'",
            f"UPDATE resume.revision SET proposal = {_to_sections('proposal')}"  # noqa: S608
            " WHERE proposal IS NOT NULL AND NOT proposal ? 'sections'",
        ],
    )


def downgrade() -> None:
    _with_rls_lifted(
        ("resume.version", "resume.revision", "resume.resume"),
        [
            f"UPDATE resume.version SET content = {_from_sections('content')}"  # noqa: S608
            " WHERE content ? 'sections'",
            f"UPDATE resume.revision SET proposal = {_from_sections('proposal')}"  # noqa: S608
            " WHERE proposal IS NOT NULL AND proposal ? 'sections'",
            "UPDATE resume.resume SET status = 'ready' WHERE status = 'filling'",
        ],
    )
    op.execute("ALTER TABLE resume.resume DROP CONSTRAINT IF EXISTS ck_resume_status")
    op.execute(
        "ALTER TABLE resume.resume ADD CONSTRAINT ck_resume_status"
        " CHECK (status IN ('drafting', 'ready', 'failed'))"
    )
    op.execute("ALTER TABLE resume.resume DROP COLUMN IF EXISTS section_plan")
