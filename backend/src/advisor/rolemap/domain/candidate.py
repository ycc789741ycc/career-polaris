"""The roles the latest analysis recommended, as queries for the market, and
the user's strengths handed over with them (ADR 0024, ADR 0027).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class RoleCandidate:
    """A role the latest analysis recommended from the user's strengths: the
    query a build searches the market and matches postings with (ADR 0024,
    Phase 8).

    ``rank`` is the analysis's own order, best fit first. Only the title
    leaves the platform, as a search; title and description are embedded to
    match the postings in scope, and ``dimension_keys`` are the strengths the
    local fit estimate reads. What a build made of it is that build's record,
    a ``CandidatePlacement``, never the candidate's.
    """

    id: uuid.UUID
    owner_id: uuid.UUID
    assessment_id: uuid.UUID
    rank: int
    title: str
    description: str
    dimension_keys: tuple[str, ...]
    created_at: datetime | None = None


@dataclass(slots=True)
class CandidateStrength:
    """One of the user's dimensions as the analysis that recommended the
    candidates scored it: what the local fit estimate reads (ADR 0027).

    A copy, handed over with the candidates and replaced with them, so the
    role map never reads ``assessment``, which sits above it (ADR 0018).
    ``weight`` is score times confidence, from 0 to 1. The fit is scored
    against the same copy, so the role map never asks ``assessment`` for it.
    """

    id: uuid.UUID
    owner_id: uuid.UUID
    assessment_id: uuid.UUID
    dimension_key: str
    name: str
    read: str
    weight: float
    # The score and confidence ``weight`` came from, which the fit is scored
    # against (ADR 0028).
    score: int
    confidence: float
