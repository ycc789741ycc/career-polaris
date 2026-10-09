"""Worker handlers for the profile module.

These run on the ``sync`` queue, the only place connector OAuth tokens can be
decrypted and the only place an uploaded document is parsed.
"""

from __future__ import annotations

import uuid
from typing import Any

from kernel.logging import get_logger

log = get_logger(__name__)


async def sync_connection(deps: Any, *, owner_id: str, kind: str) -> None:
    written = await deps.profile.sync_connection(uuid.UUID(owner_id), kind)
    log.info("profile.synced", kind=kind, evidence=written)


async def parse_resume(deps: Any, *, owner_id: str, resume_id: str) -> None:
    written = await deps.profile.parse_resume(uuid.UUID(owner_id), uuid.UUID(resume_id))
    log.info("profile.resume_parsed", evidence=written)


async def report_jira_account(deps: Any, *, owner_id: str) -> Any:
    """Report one user's Atlassian account (ADR 0061). Returns the
    ``ReportDecision``; the caller queues the sync and the next report."""
    return await deps.profile.report_jira_account(uuid.UUID(owner_id))
