"""Retire the recommended roles a build merged away but left on the map.

Owner zone, under RLS: ``rolemap.role``.

Until now reconciliation recorded a merge (``merged`` lineage, listing the
roles a kept role absorbed) but did not retire the absorbed roles. They stayed
live with their old postings: drawn as bubbles, ranked in "Top matched
openings" under their old fits, and scored again by every build's fits.

A role is retired here when it is a live ``recommended`` role, named in the
``from_role_ids`` of a ``merged`` lineage entry recorded after the role was
last updated. A role a later build kept or revived was updated since, so it
stays. Custom roles are never merged away and are not touched.

FORCE ROW LEVEL SECURITY holds even the owning migrator to the per-user policy,
so it is lifted on the two tables read and written here, and restored after.

Idempotent: a retired role is not live, so a second run changes nothing. The
downgrade does nothing. Which roles this retired is not recorded, and bringing
them back would bring the inconsistency back.
"""

from __future__ import annotations

from alembic import op

revision: str = "0024_retire_merged_roles"
down_revision: str | None = "0023_fits_in_rolemap"
branch_labels = None
depends_on = None

_TABLES = ("rolemap.role", "rolemap.role_lineage")


def upgrade() -> None:
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    op.execute(
        "UPDATE rolemap.role AS r SET retired_at = now()"
        " WHERE r.retired_at IS NULL AND r.origin = 'recommended'"
        " AND EXISTS ("
        "  SELECT 1 FROM rolemap.role_lineage AS l"
        "  WHERE l.owner_id = r.owner_id AND l.kind = 'merged'"
        "  AND l.from_role_ids ? r.id::text AND l.recorded_at > r.updated_at)"
    )
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    """Nothing to undo: see the module docstring."""
