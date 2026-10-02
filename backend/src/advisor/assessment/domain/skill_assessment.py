"""One strength report: the scores an analysis gave each dimension."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class SkillAssessment:
    id: uuid.UUID
    owner_id: uuid.UUID
    profile_version: int
    model_id: str
    template_version: str
    created_at: datetime | None = None


@dataclass(slots=True)
class AssessedScore:
    """One dimension's score within one assessment."""

    id: uuid.UUID
    owner_id: uuid.UUID
    assessment_id: uuid.UUID
    dimension_key: str
    score: int
    confidence: float
    read: str
    evidence_ids: tuple[str, ...]
