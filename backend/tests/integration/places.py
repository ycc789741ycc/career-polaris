"""Market setup for integration tests: target locations that keep a test's
postings to itself, and the fresh windows a market service is built with.

The development database is shared, so a test that chose "Taiwan" would build
from every Taiwan posting the crawler has stored. These tests store a made-up
place straight into ``market_user.market_preference`` instead, past the list
``set_target_locations`` checks against (ADR 0026). A stored name that is not
on the list matches only postings naming it, which is how a test keeps its
postings to itself.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import text

from advisor.market import FreshWindows
from kernel.db import Database


async def store_target_locations(
    database: Database, owner_id: uuid.UUID, places: list[str]
) -> None:
    """Replace ``owner_id``'s target locations with ``places``, unchecked."""
    async with database.for_user(owner_id) as session:
        await session.execute(
            text("DELETE FROM market_user.market_preference WHERE owner_id = :owner"),
            {"owner": owner_id},
        )
        for place in places:
            await session.execute(
                text(
                    "INSERT INTO market_user.market_preference "
                    "(id, owner_id, market, created_at, updated_at) "
                    "VALUES (:id, :owner, :market, now(), now())"
                ),
                {"id": uuid.uuid4(), "owner": owner_id, "market": place},
            )


# How long a fetch is reused (ADR 0027), as the defaults in .env.example.
WINDOWS = FreshWindows(search=timedelta(hours=72), board=timedelta(hours=24))
