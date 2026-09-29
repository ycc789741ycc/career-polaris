"""Worker handlers for Fill the gap. These run on the ``ai`` queue."""

from __future__ import annotations

import uuid
from typing import Any

from kernel.logging import get_logger

log = get_logger(__name__)


async def write(deps: Any, *, owner_id: str, set_id: str) -> None:
    # A failure the set can explain is recorded on it, not raised.
    await deps.gapfill.write(uuid.UUID(owner_id), uuid.UUID(set_id))
    log.info("gapfill.write_finished", set_id=set_id)
