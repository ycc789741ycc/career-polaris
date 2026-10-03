"""What Fill the gap tells the rest of the system, as domain facts.

``advisor.gapfill.infra`` maps each to its outbox name and payload.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GapAnswersSubmitted:
    """The user submitted answers for one Target. Nothing is queued for it:
    the Target's gap plan and résumé read as outdated until the user
    regenerates them (ADR 0035)."""

    owner_id: uuid.UUID
    set_id: uuid.UUID
    role_id: uuid.UUID | None
    job_posting_id: uuid.UUID | None
    evidence_ids: tuple[str, ...]
    private_job_posting_id: uuid.UUID | None = None


GapFillEvent = GapAnswersSubmitted
