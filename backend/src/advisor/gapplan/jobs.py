"""Worker handlers for gap plans. These run on the ``ai`` queue."""

from __future__ import annotations

import uuid
from typing import Any

from advisor.target import TargetRef
from kernel.logging import get_logger

log = get_logger(__name__)


async def draft(deps: Any, *, owner_id: str, plan_id: str) -> None:
    # A failure the plan can explain is recorded on it, not raised.
    await deps.gapplan.draft(uuid.UUID(owner_id), uuid.UUID(plan_id))
    log.info("gapplan.draft_finished", plan_id=plan_id)


async def regenerate(deps: Any, *, owner_id: str, role_id: str, job_posting_id: str | None) -> None:
    """Draft the Target's next plan version after answers were submitted."""
    drafted = await deps.gapplan.regenerate(uuid.UUID(owner_id), TargetRef(role_id, job_posting_id))
    log.info("gapplan.regenerate_finished", plan_id=str(drafted) if drafted else None)
