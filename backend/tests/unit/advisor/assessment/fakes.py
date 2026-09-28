"""In-memory assessment storage: the domain's repository interfaces, with no database."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from advisor.assessment.domain import (
    AnalysisRun,
    AnalysisRunFilter,
    AssessedScore,
    AssessedScoreFilter,
    AssessmentEvent,
    DimensionChange,
    DimensionChangeFilter,
    FollowUpQuestion,
    FollowUpQuestionFilter,
    QuestionRound,
    QuestionRoundFilter,
    RoleFit,
    RoleFitFilter,
    SkillAssessment,
    SkillAssessmentFilter,
    SkillDimension,
    SkillDimensionFilter,
)
from tests.unit.kernel.db.fake_repository import FakeRepository


@dataclass
class Store:
    dimensions: dict[uuid.UUID, SkillDimension] = field(default_factory=dict)
    assessments: dict[uuid.UUID, SkillAssessment] = field(default_factory=dict)
    scores: dict[uuid.UUID, AssessedScore] = field(default_factory=dict)
    changes: dict[uuid.UUID, DimensionChange] = field(default_factory=dict)
    questions: dict[uuid.UUID, FollowUpQuestion] = field(default_factory=dict)
    rounds: dict[uuid.UUID, QuestionRound] = field(default_factory=dict)
    runs: dict[uuid.UUID, AnalysisRun] = field(default_factory=dict)
    fits: dict[uuid.UUID, RoleFit] = field(default_factory=dict)
    events: list[AssessmentEvent] = field(default_factory=list)


class FakeDimensions(FakeRepository[SkillDimension, SkillDimensionFilter]):
    owner_field = "owner_id"
    noun = "skill dimension"

    def matches(self, entity: SkillDimension, filter: SkillDimensionFilter) -> bool:
        return filter.keys is None or entity.key in filter.keys


class FakeAssessments(FakeRepository[SkillAssessment, SkillAssessmentFilter]):
    updated_field = None
    owner_field = "owner_id"
    noun = "assessment"

    def matches(self, entity: SkillAssessment, filter: SkillAssessmentFilter) -> bool:
        return True


class FakeScores(FakeRepository[AssessedScore, AssessedScoreFilter]):
    created_field = "id"
    updated_field = None
    owner_field = "owner_id"
    noun = "dimension score"

    def matches(self, entity: AssessedScore, filter: AssessedScoreFilter) -> bool:
        return filter.assessment_id is None or entity.assessment_id == filter.assessment_id


class FakeChanges(FakeRepository[DimensionChange, DimensionChangeFilter]):
    created_field = "recorded_at"
    updated_field = None
    owner_field = "owner_id"
    noun = "dimension change"

    def matches(self, entity: DimensionChange, filter: DimensionChangeFilter) -> bool:
        return filter.assessment_id is None or entity.assessment_id == filter.assessment_id


class FakeQuestions(FakeRepository[FollowUpQuestion, FollowUpQuestionFilter]):
    updated_field = None
    owner_field = "owner_id"
    noun = "question"

    def matches(self, entity: FollowUpQuestion, filter: FollowUpQuestionFilter) -> bool:
        return (
            filter.is_answered is None or (entity.answered_at is not None) == filter.is_answered
        ) and (filter.is_retired is None or (entity.retired_at is not None) == filter.is_retired)


class FakeRounds(FakeRepository[QuestionRound, QuestionRoundFilter]):
    updated_field = None
    owner_field = "owner_id"
    noun = "question round"

    def matches(self, entity: QuestionRound, filter: QuestionRoundFilter) -> bool:
        return filter.status is None or entity.status is filter.status


class FakeRuns(FakeRepository[AnalysisRun, AnalysisRunFilter]):
    created_field = "started_at"
    updated_field = None
    owner_field = "owner_id"
    noun = "analysis run"

    def matches(self, entity: AnalysisRun, filter: AnalysisRunFilter) -> bool:
        return filter.status is None or entity.status is filter.status


class FakeFits(FakeRepository[RoleFit, RoleFitFilter]):
    updated_field = None
    owner_field = "owner_id"
    noun = "fit"

    def matches(self, entity: RoleFit, filter: RoleFitFilter) -> bool:
        return (
            (filter.role_id is None or entity.role_id == filter.role_id)
            and (
                filter.private_posting_id is None
                or entity.private_posting_id == filter.private_posting_id
            )
            and (filter.assessment_id is None or entity.assessment_id == filter.assessment_id)
        )


class FakeOwner:
    def __init__(self, store: Store, owner_id: uuid.UUID) -> None:
        self.dimensions = FakeDimensions(store.dimensions, owner_id=owner_id)
        self.assessments = FakeAssessments(store.assessments, owner_id=owner_id)
        self.scores = FakeScores(store.scores, owner_id=owner_id)
        self.changes = FakeChanges(store.changes, owner_id=owner_id)
        self.questions = FakeQuestions(store.questions, owner_id=owner_id)
        self.rounds = FakeRounds(store.rounds, owner_id=owner_id)
        self.runs = FakeRuns(store.runs, owner_id=owner_id)
        self.fits = FakeFits(store.fits, owner_id=owner_id)
        self.pending: list[AssessmentEvent] = []

    def record(self, event: AssessmentEvent) -> None:
        self.pending.append(event)


class FakeAssessmentUnitOfWork:
    def __init__(self, store: Store | None = None) -> None:
        self.store = store or Store()

    @asynccontextmanager
    async def for_owner(self, owner_id: uuid.UUID) -> AsyncIterator[FakeOwner]:
        scope = FakeOwner(self.store, owner_id)
        yield scope
        self.store.events.extend(scope.pending)
