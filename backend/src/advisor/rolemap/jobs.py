"""Worker handlers for the role map. These run on the ``ai`` queue."""

from __future__ import annotations

import uuid
from typing import Any

from kernel.logging import get_logger

log = get_logger(__name__)


async def recluster(deps: Any, *, owner_id: str, build_id: str) -> None:
    # A failure the build can explain is recorded on it, not raised.
    roles = await deps.rolemap.build(uuid.UUID(owner_id), uuid.UUID(build_id))
    log.info("rolemap.reclustered", build_id=build_id, roles=len(roles))
