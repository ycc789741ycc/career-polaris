"""What assessment tells the rest of the system, as domain facts.

``advisor.assessment.infra`` maps each to its outbox name and payload.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AssessmentCompleted:
    owner_id: uuid.UUID
    assessment_id: uuid.UUID
    dimensions: int
    model_id: str


@dataclass(frozen=True, slots=True)
class DimensionsChanged:
    owner_id: uuid.UUID
    added_or_renamed: int
    retired: int


@dataclass(frozen=True, slots=True)
class QuestionsRaised:
    owner_id: uuid.UUID
    assessment_id: uuid.UUID
    count: int


@dataclass(frozen=True, slots=True)
class QuestionAnswered:
    owner_id: uuid.UUID
    question_id: uuid.UUID
    dimension_key: str


@dataclass(frozen=True, slots=True)
class RoleFitsComputed:
    owner_id: uuid.UUID
    roles: int


AssessmentEvent = (
    AssessmentCompleted | DimensionsChanged | QuestionsRaised | QuestionAnswered | RoleFitsComputed
)
