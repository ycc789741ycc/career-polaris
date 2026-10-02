"""Worker handlers for Target. These run on the ``ai`` queue."""

from __future__ import annotations

import uuid
from typing import Any

from kernel.logging import get_logger

log = get_logger(__name__)


async def evaluate_own_posting(deps: Any, *, owner_id: str, evaluation_id: str) -> None:
    """Read and score a posting of the user's own (Phase 8, ADR 0033). A
    failure the run can explain is recorded on it, not raised."""
    await deps.target.evaluate_own_posting(uuid.UUID(owner_id), uuid.UUID(evaluation_id))
    log.info("target.own_posting_evaluated", evaluation_id=evaluation_id)
