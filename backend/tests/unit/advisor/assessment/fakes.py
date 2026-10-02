"""In-memory assessment storage: the domain's repository interfaces, with no database."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from advisor.assessment.domain import (
    AnalysisRun,
    AnalysisRunFilter,
    AnalysisRunRepository,
    AssessedScore,
    AssessedScoreFilter,
    AssessedScoreRepository,
    AssessmentEvent,
    AssessmentUnitOfWork,
    DimensionChange,
    DimensionChangeFilter,
    DimensionChangeRepository,
    OwnerAssessment,
    SkillAssessment,
    SkillAssessmentFilter,
    SkillAssessmentRepository,
    SkillDimension,
    SkillDimensionFilter,
    SkillDimensionRepository,
)
from tests.unit.kernel.db.fake_repository import FakeRepository


@dataclass
class Store:
    dimensions: dict[uuid.UUID, SkillDimension] = field(default_factory=dict)
    assessments: dict[uuid.UUID, SkillAssessment] = field(default_factory=dict)
    scores: dict[uuid.UUID, AssessedScore] = field(default_factory=dict)
    changes: dict[uuid.UUID, DimensionChange] = field(default_factory=dict)
    runs: dict[uuid.UUID, AnalysisRun] = field(default_factory=dict)
    events: list[AssessmentEvent] = field(default_factory=list)


class FakeDimensions(
    FakeRepository[SkillDimension, SkillDimensionFilter],
    SkillDimensionRepository,
):
    owner_field = "owner_id"
    noun = "skill dimension"

    def matches(self, entity: SkillDimension, filter: SkillDimensionFilter) -> bool:
        return filter.keys is None or entity.key in filter.keys


class FakeAssessments(
    FakeRepository[SkillAssessment, SkillAssessmentFilter],
    SkillAssessmentRepository,
):
    updated_field = None
    owner_field = "owner_id"
    noun = "assessment"

    def matches(self, entity: SkillAssessment, filter: SkillAssessmentFilter) -> bool:
        return True


class FakeScores(FakeRepository[AssessedScore, AssessedScoreFilter], AssessedScoreRepository):
    created_field = "id"
    updated_field = None
    owner_field = "owner_id"
    noun = "dimension score"

    def matches(self, entity: AssessedScore, filter: AssessedScoreFilter) -> bool:
        return filter.assessment_id is None or entity.assessment_id == filter.assessment_id


class FakeChanges(
    FakeRepository[DimensionChange, DimensionChangeFilter],
    DimensionChangeRepository,
):
    created_field = "recorded_at"
    updated_field = None
    owner_field = "owner_id"
    noun = "dimension change"

    def matches(self, entity: DimensionChange, filter: DimensionChangeFilter) -> bool:
        return filter.assessment_id is None or entity.assessment_id == filter.assessment_id


class FakeRuns(FakeRepository[AnalysisRun, AnalysisRunFilter], AnalysisRunRepository):
    created_field = "started_at"
    updated_field = None
    owner_field = "owner_id"
    noun = "analysis run"

    def matches(self, entity: AnalysisRun, filter: AnalysisRunFilter) -> bool:
        return filter.status is None or entity.status is filter.status


class FakeOwner(OwnerAssessment):
    def __init__(self, store: Store, owner_id: uuid.UUID) -> None:
        self.dimensions = FakeDimensions(store.dimensions, owner_id=owner_id)
        self.assessments = FakeAssessments(store.assessments, owner_id=owner_id)
        self.scores = FakeScores(store.scores, owner_id=owner_id)
        self.changes = FakeChanges(store.changes, owner_id=owner_id)
        self.runs = FakeRuns(store.runs, owner_id=owner_id)
        self.pending: list[AssessmentEvent] = []

    def record(self, event: AssessmentEvent) -> None:
        self.pending.append(event)


class FakeAssessmentUnitOfWork(AssessmentUnitOfWork):
    def __init__(self, store: Store | None = None) -> None:
        self.store = store or Store()

    @asynccontextmanager
    async def for_owner(self, owner_id: uuid.UUID) -> AsyncIterator[FakeOwner]:
        scope = FakeOwner(self.store, owner_id)
        yield scope
        self.store.events.extend(scope.pending)
