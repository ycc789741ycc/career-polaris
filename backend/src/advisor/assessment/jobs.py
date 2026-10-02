"""Worker handlers for the assessment. These run on the ``ai`` queue."""

from __future__ import annotations

import uuid
from typing import Any

from kernel.logging import get_logger

log = get_logger(__name__)


async def run(deps: Any, *, owner_id: str, run_id: str) -> None:
    """Analyse for one recorded run. A failure is recorded on the run."""
    assessment = await deps.assessment.analyse(uuid.UUID(owner_id), uuid.UUID(run_id))
    if assessment is None:
        return
    log.info(
        "assessment.completed",
        dimensions=len(assessment.dimensions),
        model_id=assessment.model_id,
    )
