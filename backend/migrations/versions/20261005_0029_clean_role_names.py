"""Take where or how a role is worked off its stored name (Phase 8).

Owner zone, under RLS: ``rolemap.role``.

The model that names a role sees each posting's location, and sometimes put it
in the name: "Senior Data Scientist / AI Engineer (Remote)". ``role_extraction``
v2 tells it not to, and ``parse_role_name`` takes a trailing work-arrangement
or gender tag off every name a build stores from now on. This applies the same
rule to the names already stored, so the map does not wait for each role's
openings to change before it reads right.

The pattern copies ``advisor.rolemap.domain.role._TRAILING_TAG`` as it stands
today, rather than importing it, so this migration does the same thing
whenever it runs. It is applied three times, for a name with several tags,
and a name that would be left empty keeps what it had.

FORCE ROW LEVEL SECURITY holds even the owning migrator to the per-user policy,
so it is lifted on the table while it is written, and restored after.

Idempotent: a clean name matches nothing. The downgrade does nothing; the old
names are not kept, and bringing the tags back would undo the fix.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0029_clean_role_names"
down_revision: str | None = "0028_opening_fits"
branch_labels = None
depends_on = None

_TAG = (
    r"(?:fully\s+|100%\s+)?remote|hybrid|on[\s-]?site|in[\s-]office|worldwide|anywhere"
    r"|wfh|work\s+from\s+home|[mfwdx](?:\s*/\s*[mfwdx]){1,3}|all\s+genders"
)
_TRAILING = (
    rf"\s*(?:[(\[]\s*(?:{_TAG})(?:\s*[,/&|]\s*[^)\]]*)?\s*[)\]]"
    rf"|\s[-\u2013\u2014|:]\s*(?:{_TAG})|,\s*(?:{_TAG}))\s*$"
)


def upgrade() -> None:
    # The pattern goes as a bind parameter: written into the SQL, its "(?:"
    # groups would read as parameters themselves.
    cleaned = "name"
    for _ in range(3):
        cleaned = f"btrim(regexp_replace({cleaned}, :pattern, '', 'i'))"
    op.execute("ALTER TABLE rolemap.role NO FORCE ROW LEVEL SECURITY")
    op.get_bind().execute(
        sa.text(
            f"UPDATE rolemap.role SET name = {cleaned}"  # noqa: S608
            f" WHERE {cleaned} <> name AND {cleaned} <> ''"
        ),
        {"pattern": _TRAILING},
    )
    op.execute("ALTER TABLE rolemap.role FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    """Nothing to undo: see the module docstring."""
