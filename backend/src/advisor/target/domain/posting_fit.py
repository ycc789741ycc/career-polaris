"""How the user measures up to a posting of their own (Phase 8, ADR 0033).

Two records, kept apart as ADR 0030 decided:

- ``PostingRequirementFit`` is the AI's evaluation: the JD's requirements
  mapped onto the user's dimensions, with a target for each. The role map
  makes it, with the projection every fit uses (ADR 0028); Target stores it.
- ``OwnPostingFit`` is worked out from it locally, by the role map's fit
  rules: the score, gaps and uncovered requirements the Advisor plans
  against. It is never an AI call.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class PostingRequirement:
    """Free text read out of a posting of the user's own: what its JD asks
    for. It has no dimension; the fit maps it onto the user's."""

    id: uuid.UUID
    owner_id: uuid.UUID
    private_job_posting_id: uuid.UUID
    statement: str
    weight: float
    expected_level: str


@dataclass(slots=True)
class PostingRequirementFit:
    """The AI's evaluation of a posting of the user's own: its requirements
    mapped onto the user's dimensions, with a target for each. Every one taken
    is kept; the newest is the current one."""

    id: uuid.UUID
    owner_id: uuid.UUID
    private_job_posting_id: uuid.UUID
    assessment_id: uuid.UUID
    requirements: tuple[dict[str, Any], ...]
    requirement_map: dict[str, str | None]
    target_profile: dict[str, int]
    reasoning: str
    model_id: str
    template_version: str
    # A hash of what it read: the requirements and the fit prompt's version.
    requirements_digest: str | None = None
    created_at: datetime | None = None

    def is_current(self, *, assessment_id: uuid.UUID, requirements_digest: str) -> bool:
        """Whether rescoring would read the same requirements and the same
        analysis's scores, and so come out the same."""
        return (
            self.assessment_id == assessment_id
            and self.requirements_digest is not None
            and self.requirements_digest == requirements_digest
        )


@dataclass(slots=True)
class OwnPostingFit:
    """The user's fit to a posting of their own, worked out locally from its
    ``PostingRequirementFit`` (``source_fit_id``) against the scores of the
    analysis ``assessment_id`` names. Every one is kept; the newest is current.
    """

    id: uuid.UUID
    owner_id: uuid.UUID
    private_job_posting_id: uuid.UUID
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
        """Scored against an analysis older than the latest: worth rescoring,
        though never rescored unasked."""
        return latest_assessment_id is not None and self.assessment_id != latest_assessment_id
