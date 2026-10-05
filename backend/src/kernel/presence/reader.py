"""Whether the worker and the crawler are up, as the api sees it."""

from __future__ import annotations

from sqlalchemy import text

from kernel.config import Unit
from kernel.db import Database
from kernel.presence.view import PresenceView, UnitPresence


async def get_presence(database: Database, *, away_after_seconds: float) -> PresenceView:
    """Read every heartbeat. A process is up while its last beat is newer than
    ``away_after_seconds``, measured on the database's clock, which wrote it."""
    async with database.shared() as session:
        rows = await session.execute(
            text(
                "SELECT unit,"
                " min(started_at) FILTER (WHERE seen_at > now() - make_interval(secs => :away)),"
                " max(seen_at)"
                " FROM presence.process GROUP BY unit"
            ),
            {"away": away_after_seconds},
        )
        found = {str(unit): UnitPresence(since, seen) for unit, since, seen in rows}
    nobody = UnitPresence(online_since=None, seen_at=None)
    return PresenceView(
        worker=found.get(str(Unit.WORKER), nobody),
        crawler=found.get(str(Unit.CRAWLER), nobody),
    )
