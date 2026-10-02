"""The roles the latest analysis recommended, and the user's strengths handed
over with them (ADR 0024, ADR 0027).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class RoleCandidate:
    """A role the latest analysis recommended from the user's strengths, before
    the market is searched for it (ADR 0024).

    ``rank`` is the analysis's own order, best fit first. A build places the
    candidate on the role it became, or leaves it unplaced when the user's
    target locations have too few openings for it.
    """

    id: uuid.UUID
    owner_id: uuid.UUID
    assessment_id: uuid.UUID
    rank: int
    title: str
    description: str
    dimension_keys: tuple[str, ...]
    role_id: uuid.UUID | None = None
    opening_count: int = 0
    # How well its openings read like the user's strengths, by the local
    # estimate that chose the k (ADR 0027); never shown as a fit.
    fit_estimate: float | None = None
    created_at: datetime | None = None

    @property
    def is_placed(self) -> bool:
        return self.role_id is not None

    def placed(
        self, *, role_id: uuid.UUID, opening_count: int, fit_estimate: float | None = None
    ) -> None:
        self.role_id = role_id
        self.opening_count = opening_count
        self.fit_estimate = fit_estimate

    def unplaced(self, *, opening_count: int = 0, fit_estimate: float | None = None) -> None:
        self.role_id = None
        self.opening_count = opening_count
        self.fit_estimate = fit_estimate


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
