"""How the user measures up to one opening in a role (ADR 0073).

An opening is scored as a posting of the user's own is (ADR 0034), from its
own description, when its gap analysis runs in Fill the gap. Three records:

- ``OpeningRequirement`` is what the opening's description asks for, read
  once and kept, even after the posting leaves the market.
- ``OpeningRequirementFit`` is the AI's evaluation: those requirements mapped
  onto the user's dimensions, with a target for each. Every one taken is kept;
  the newest is current.
- ``OpeningFit`` is worked out from it locally, by the role map's fit rules:
  the score, gaps and uncovered requirements the Advisor plans against.

They are keyed on the shared posting's id, not its role: what an opening asks
for, and the user's fit to it, do not depend on the role a build put it in.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class OpeningRequirement:
    """Free text read out of an opening's description. It has no dimension;
    the fit maps it onto the user's."""

    id: uuid.UUID
    owner_id: uuid.UUID
    job_posting_id: uuid.UUID
    statement: str
    weight: float
    expected_level: str


@dataclass(slots=True)
class OpeningRequirementFit:
    """The AI's evaluation of an opening: its requirements mapped onto the
    user's dimensions, with a target for each."""

    id: uuid.UUID
    owner_id: uuid.UUID
    job_posting_id: uuid.UUID
    assessment_id: uuid.UUID
    requirements: tuple[dict[str, Any], ...]
    requirement_map: dict[str, str | None]
    target_profile: dict[str, int]
    reasoning: str
    model_id: str
    template_version: str
    # A hash of what it read: the requirements and the fit prompt's version.
    requirements_digest: str
    created_at: datetime | None = None

    def is_current(self, *, assessment_id: uuid.UUID, requirements_digest: str) -> bool:
        """Whether rescoring would read the same requirements and the same
        analysis's scores, and so come out the same."""
        return (
            self.assessment_id == assessment_id and self.requirements_digest == requirements_digest
        )


@dataclass(slots=True)
class OpeningFit:
    """The user's fit to an opening, worked out locally from its
    ``OpeningRequirementFit`` (``source_fit_id``) against the scores of the
    analysis ``assessment_id`` names. Every one is kept; the newest is current.
    """

    id: uuid.UUID
    owner_id: uuid.UUID
    job_posting_id: uuid.UUID
    source_fit_id: uuid.UUID
    assessment_id: uuid.UUID
    score: int
    requirements: tuple[dict[str, Any], ...]
    requirement_map: dict[str, str | None]
    target_profile: dict[str, int]
    gaps: tuple[dict[str, Any], ...]
    uncovered: tuple[dict[str, Any], ...]
    created_at: datetime | None = None

    def is_stale(self, latest_assessment_id: uuid.UUID | None) -> bool:
        """Scored against an analysis older than the latest: the next gap
        analysis rescores it."""
        return latest_assessment_id is not None and self.assessment_id != latest_assessment_id
