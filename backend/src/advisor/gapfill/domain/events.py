"""What Fill the gap tells the rest of the system, as domain facts.

``advisor.gapfill.infra`` maps each to its outbox name and payload.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GapAnswersSubmitted:
    """The user submitted answers for one Target. The dispatcher regenerates
    that Target's gap plan and résumé, each only if the user has one."""

    owner_id: uuid.UUID
    set_id: uuid.UUID
    role_id: uuid.UUID
    job_posting_id: uuid.UUID | None
    evidence_ids: tuple[str, ...]


GapFillEvent = GapAnswersSubmitted
