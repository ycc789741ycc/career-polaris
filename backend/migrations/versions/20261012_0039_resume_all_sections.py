"""A résumé holds every section, each shown or hidden (ADR 0043).

* Every slot in ``resume.resume.section_plan`` gains ``is_shown``: the
  sections a résumé has now are shown, and every built-in kind it lacks is
  appended after them, hidden. The column's default is a new résumé's plan:
  summary, experience and skills shown, the rest hidden.
* Every saved version's ``content`` and every chat revision's stored
  ``proposal`` do the same with their sections: the ones there are shown, and
  the missing built-in kinds are appended hidden and empty.

Row-level security is lifted for the rewrite, as the rows are every user's.
Downgrading drops the hidden sections, with whatever was written in them, and
the flag, and puts the old default back.
"""

from __future__ import annotations

from alembic import op

revision: str = "0039_resume_all_sections"
down_revision: str | None = "0038_advisor_jobs"
branch_labels = None
depends_on = None

# In the order a résumé holds the ones it does not show.
_BUILT_IN_KINDS = (
    "summary",
    "experience",
    "side_projects",
    "open_source",
    "education",
    "talks_and_writing",
    "skills",
    "certifications",
)
_DEFAULT_SHOWN = ("summary", "experience", "skills")

_OLD_DEFAULT = (
    """'[{"kind": "summary", "title": null}, {"kind": "experience", "title": null},"""
    """ {"kind": "skills", "title": null}]'::jsonb"""
)
_NEW_DEFAULT = (
    "'["
    + ", ".join(
        f'{{"kind": "{k}", "title": null, "is_shown": {str(k in _DEFAULT_SHOWN).lower()}}}'
        for k in (*_DEFAULT_SHOWN, *(k for k in _BUILT_IN_KINDS if k not in _DEFAULT_SHOWN))
    )
    + "]'::jsonb"
)
_KINDS = "ARRAY[" + ", ".join(f"'{k}'" for k in _BUILT_IN_KINDS) + "]"


def _held(column: str, *, empty_section: bool) -> str:
    """SQL for the array held in ``column``: each element shown, then every
    built-in kind it lacks, hidden — as a slot, or as an empty section."""
    missing = (
        "jsonb_build_object('kind', k, 'title', null, 'text', '', 'entries', '[]'::jsonb,"
        " 'items', '[]'::jsonb, 'bullets', '[]'::jsonb, 'is_shown', false)"
        if empty_section
        else "jsonb_build_object('kind', k, 'title', null, 'is_shown', false)"
    )
    return f"""(
        coalesce((
            SELECT jsonb_agg(
                CASE WHEN s ? 'is_shown' THEN s ELSE s || '{{"is_shown": true}}'::jsonb END
                ORDER BY n)
            FROM jsonb_array_elements({column}) WITH ORDINALITY AS x(s, n)), '[]'::jsonb)
        || coalesce((
            SELECT jsonb_agg({missing} ORDER BY o)
            FROM unnest({_KINDS}) WITH ORDINALITY AS b(k, o)
            WHERE NOT EXISTS (
                SELECT 1 FROM jsonb_array_elements({column}) AS y(t)
                WHERE t->>'kind' = k)), '[]'::jsonb))"""  # noqa: S608 - fixed names


def _shown_only(column: str) -> str:
    """SQL for the array held in ``column`` with hidden elements and the flag
    gone."""
    return f"""coalesce((
        SELECT jsonb_agg(s - 'is_shown' ORDER BY n)
        FROM jsonb_array_elements({column}) WITH ORDINALITY AS x(s, n)
        WHERE coalesce((s->>'is_shown')::boolean, true)), '[]'::jsonb)"""  # noqa: S608


def _with_rls_lifted(tables: tuple[str, ...], statements: list[str]) -> None:
    for table in tables:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    for statement in statements:
        op.execute(statement)
    for table in tables:
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


_CONTENT = "content->'sections'"
_PROPOSAL = "proposal->'sections'"


def upgrade() -> None:
    op.execute(f"ALTER TABLE resume.resume ALTER COLUMN section_plan SET DEFAULT {_NEW_DEFAULT}")
    _with_rls_lifted(
        ("resume.resume", "resume.version", "resume.revision"),
        [
            "UPDATE resume.resume"  # noqa: S608 - fixed names
            f" SET section_plan = {_held('section_plan', empty_section=False)}",
            "UPDATE resume.version SET content = jsonb_set(content, '{sections}',"  # noqa: S608
            f" {_held(_CONTENT, empty_section=True)})"
            " WHERE content ? 'sections'",
            "UPDATE resume.revision SET proposal = jsonb_set(proposal, '{sections}',"  # noqa: S608
            f" {_held(_PROPOSAL, empty_section=True)})"
            " WHERE proposal IS NOT NULL AND proposal ? 'sections'",
        ],
    )


def downgrade() -> None:
    _with_rls_lifted(
        ("resume.resume", "resume.version", "resume.revision"),
        [
            f"UPDATE resume.resume SET section_plan = {_shown_only('section_plan')}",  # noqa: S608
            "UPDATE resume.version SET content = jsonb_set(content, '{sections}',"  # noqa: S608
            f" {_shown_only(_CONTENT)})"
            " WHERE content ? 'sections'",
            "UPDATE resume.revision SET proposal = jsonb_set(proposal, '{sections}',"  # noqa: S608
            f" {_shown_only(_PROPOSAL)})"
            " WHERE proposal IS NOT NULL AND proposal ? 'sections'",
        ],
    )
    op.execute(f"ALTER TABLE resume.resume ALTER COLUMN section_plan SET DEFAULT {_OLD_DEFAULT}")
