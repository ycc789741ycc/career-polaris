"""How assessment's use cases reach stored data: interfaces in domain terms.

Every repository has the same six methods (ADR 0011): ``create``, ``get``,
``get_list`` (newest first, paged), ``get_count``, ``update`` and ``delete``,
over one frozen filter per aggregate whose unset fields do not filter. Scores
have no creation time stored, so they list by id; callers order them by key.

All assessment data is owner-zone, so the unit of work has one scope: one
user's data, in one transaction. Events recorded in it are committed with it.
"""

from __future__ import annotations

import uuid
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Protocol

from advisor.assessment.domain.entities import (
    AssessedScore,
    DimensionChange,
    FollowUpQuestion,
    QuestionRound,
    QuestionRoundStatus,
    RoleFit,
    SkillAssessment,
    SkillDimension,
)
from advisor.assessment.domain.events import AssessmentEvent


class Repository[Entity, Filter](Protocol):
    """The six methods, as every assessment repository has them."""

    async def create(self, entity: Entity) -> Entity: ...

    async def get(self, entity_id: uuid.UUID) -> Entity | None: ...

    async def get_list(
        self, filter: Filter, page: int = 1, page_size: int | None = None
    ) -> list[Entity]: ...

    async def get_count(self, filter: Filter) -> int: ...

    async def update(self, entity: Entity) -> Entity: ...

    async def delete(self, entity_id: uuid.UUID) -> None: ...


@dataclass(frozen=True, slots=True)
class SkillDimensionFilter:
    keys: tuple[str, ...] | None = None


class SkillDimensionRepository(Repository[SkillDimension, SkillDimensionFilter], Protocol): ...


@dataclass(frozen=True, slots=True)
class SkillAssessmentFilter:
    """Nothing to filter on yet: the owner scope and newest-first order are
    what "latest" and "history" need."""


class SkillAssessmentRepository(Repository[SkillAssessment, SkillAssessmentFilter], Protocol): ...


@dataclass(frozen=True, slots=True)
class AssessedScoreFilter:
    assessment_id: uuid.UUID | None = None


class AssessedScoreRepository(Repository[AssessedScore, AssessedScoreFilter], Protocol): ...


@dataclass(frozen=True, slots=True)
class DimensionChangeFilter:
    assessment_id: uuid.UUID | None = None


class DimensionChangeRepository(Repository[DimensionChange, DimensionChangeFilter], Protocol): ...


@dataclass(frozen=True, slots=True)
class FollowUpQuestionFilter:
    is_answered: bool | None = None
    is_retired: bool | None = None


class FollowUpQuestionRepository(
    Repository[FollowUpQuestion, FollowUpQuestionFilter], Protocol
): ...


@dataclass(frozen=True, slots=True)
class QuestionRoundFilter:
    status: QuestionRoundStatus | None = None


class QuestionRoundRepository(Repository[QuestionRound, QuestionRoundFilter], Protocol): ...


@dataclass(frozen=True, slots=True)
class RoleFitFilter:
    role_id: uuid.UUID | None = None
    private_posting_id: uuid.UUID | None = None
    assessment_id: uuid.UUID | None = None


class RoleFitRepository(Repository[RoleFit, RoleFitFilter], Protocol): ...


class OwnerAssessment(Protocol):
    @property
    def dimensions(self) -> SkillDimensionRepository: ...

    @property
    def assessments(self) -> SkillAssessmentRepository: ...

    @property
    def scores(self) -> AssessedScoreRepository: ...

    @property
    def changes(self) -> DimensionChangeRepository: ...

    @property
    def questions(self) -> FollowUpQuestionRepository: ...

    @property
    def rounds(self) -> QuestionRoundRepository: ...

    @property
    def fits(self) -> RoleFitRepository: ...

    def record(self, event: AssessmentEvent) -> None: ...


class AssessmentUnitOfWork(Protocol):
    def for_owner(self, owner_id: uuid.UUID) -> AbstractAsyncContextManager[OwnerAssessment]: ...
