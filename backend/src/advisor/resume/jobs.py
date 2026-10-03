"""Worker handlers for the Resume Advisor.

Writing runs on the ``ai`` queue; PDF export on ``docs``. A failure the
résumé or export can explain is recorded on it, not raised.
"""

from __future__ import annotations

import uuid
from typing import Any

from advisor.resume.service import SectionSlot
from kernel.logging import get_logger

log = get_logger(__name__)


async def generate(deps: Any, *, owner_id: str, resume_id: str) -> None:
    await deps.resume.generate(uuid.UUID(owner_id), uuid.UUID(resume_id))
    log.info("resume.generate_finished", resume_id=resume_id)


async def fill_section(
    deps: Any, *, owner_id: str, resume_id: str, kind: str, title: str | None = None
) -> None:
    """Write one added section from the sources (ADR 0039)."""
    slot = SectionSlot.from_dict({"kind": kind, "title": title})
    await deps.resume.fill_section(uuid.UUID(owner_id), uuid.UUID(resume_id), slot)
    log.info("resume.fill_section_finished", resume_id=resume_id, kind=kind)


async def export(deps: Any, *, owner_id: str, export_id: str) -> None:
    await deps.resume.export(uuid.UUID(owner_id), uuid.UUID(export_id))
    log.info("resume.export_finished", export_id=export_id)
