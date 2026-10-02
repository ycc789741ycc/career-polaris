"""Worker handlers for the role map: builds and fits run on the ``ai`` queue,
checks on the market on ``sync``."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from kernel.logging import get_logger

log = get_logger(__name__)


async def recluster(deps: Any, *, owner_id: str, build_id: str) -> None:
    # A failure the build can explain is recorded on it, not raised.
    roles = await deps.rolemap.build(uuid.UUID(owner_id), uuid.UUID(build_id))
    log.info("rolemap.reclustered", build_id=build_id, roles=len(roles))


async def await_market(deps: Any, *, owner_id: str, build_id: str) -> Any:
    """Check whether a build waiting for the market may start (ADR 0027).
    Returns a ``MarketWait``; the caller queues the build or checks again."""
    return await deps.rolemap.check_market(
        uuid.UUID(owner_id),
        uuid.UUID(build_id),
        deadline=timedelta(seconds=deps.settings.market_wait_seconds),
    )


async def compute_fits(deps: Any, *, owner_id: str) -> None:
    """Score the fits of the build that just closed (ADR 0028)."""
    fits = await deps.rolemap.compute_fits(uuid.UUID(owner_id))
    log.info("rolemap.fits_computed", fits=len(fits))
