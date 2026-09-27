"""SQLAlchemy implementations of assessment's repositories.

The six methods come from ``kernel.db.repository.SqlAlchemyRepository``. Every
assessment table is owner-zone, so every repository here is bound to one owner.
Dimension scores have no creation time stored, so they sort by id.
"""

from __future__ import annotations

import uuid
from typing import ClassVar

from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.elements import ColumnElement

from advisor.assessment.domain import (
    AssessedScore,
    AssessedScoreFilter,
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
from advisor.assessment.infra import mappers, models
from kernel.db.repository import SqlAlchemyRepository


class SqlAlchemySkillDimensionRepository(
    SqlAlchemyRepository[SkillDimension, models.SkillDimension, SkillDimensionFilter]
):
    model = models.SkillDimension
    id_column = models.SkillDimension.id
    created_column = models.SkillDimension.created_at
    owner_column: ClassVar[InstrumentedAttribute[uuid.UUID] | None] = models.SkillDimension.owner_id
    noun = "skill dimension"

    def to_entity(self, row: models.SkillDimension) -> SkillDimension:
        return mappers.dimension(row)

    def to_row(self, entity: SkillDimension) -> models.SkillDimension:
        return mappers.dimension_row(entity)

    def apply(self, row: models.SkillDimension, entity: SkillDimension) -> None:
        mappers.apply_dimension(row, entity)

    def id_of(self, entity: SkillDimension) -> uuid.UUID:
        return entity.id

    def conditions(self, filter: SkillDimensionFilter) -> list[ColumnElement[bool]]:
        if filter.keys is None:
            return []
        return [models.SkillDimension.key.in_(filter.keys)]


class SqlAlchemySkillAssessmentRepository(
    SqlAlchemyRepository[SkillAssessment, models.SkillAssessment, SkillAssessmentFilter]
):
    model = models.SkillAssessment
    id_column = models.SkillAssessment.id
    created_column = models.SkillAssessment.created_at
    owner_column: ClassVar[InstrumentedAttribute[uuid.UUID] | None] = (
        models.SkillAssessment.owner_id
    )
    noun = "assessment"

    def to_entity(self, row: models.SkillAssessment) -> SkillAssessment:
        return mappers.assessment(row)

    def to_row(self, entity: SkillAssessment) -> models.SkillAssessment:
        return mappers.assessment_row(entity)

    def apply(self, row: models.SkillAssessment, entity: SkillAssessment) -> None:
        mappers.apply_assessment(row, entity)

    def id_of(self, entity: SkillAssessment) -> uuid.UUID:
        return entity.id

    def conditions(self, filter: SkillAssessmentFilter) -> list[ColumnElement[bool]]:
        return []


class SqlAlchemyAssessedScoreRepository(
    SqlAlchemyRepository[AssessedScore, models.DimensionScore, AssessedScoreFilter]
):
    model = models.DimensionScore
    id_column = models.DimensionScore.id
    created_column = models.DimensionScore.id
    owner_column: ClassVar[InstrumentedAttribute[uuid.UUID] | None] = models.DimensionScore.owner_id
    noun = "dimension score"

    def to_entity(self, row: models.DimensionScore) -> AssessedScore:
        return mappers.score(row)

    def to_row(self, entity: AssessedScore) -> models.DimensionScore:
        return mappers.score_row(entity)

    def apply(self, row: models.DimensionScore, entity: AssessedScore) -> None:
        mappers.apply_score(row, entity)

    def id_of(self, entity: AssessedScore) -> uuid.UUID:
        return entity.id

    def conditions(self, filter: AssessedScoreFilter) -> list[ColumnElement[bool]]:
        if filter.assessment_id is None:
            return []
        return [models.DimensionScore.assessment_id == filter.assessment_id]


class SqlAlchemyDimensionChangeRepository(
    SqlAlchemyRepository[DimensionChange, models.DimensionLineage, DimensionChangeFilter]
):
    model = models.DimensionLineage
    id_column = models.DimensionLineage.id
    created_column = models.DimensionLineage.recorded_at
    owner_column: ClassVar[InstrumentedAttribute[uuid.UUID] | None] = (
        models.DimensionLineage.owner_id
    )
    noun = "dimension change"

    def to_entity(self, row: models.DimensionLineage) -> DimensionChange:
        return mappers.change(row)

    def to_row(self, entity: DimensionChange) -> models.DimensionLineage:
        return mappers.change_row(entity)

    def apply(self, row: models.DimensionLineage, entity: DimensionChange) -> None:
        mappers.apply_change(row, entity)

    def id_of(self, entity: DimensionChange) -> uuid.UUID:
        return entity.id

    def conditions(self, filter: DimensionChangeFilter) -> list[ColumnElement[bool]]:
        if filter.assessment_id is None:
            return []
        return [models.DimensionLineage.assessment_id == filter.assessment_id]


class SqlAlchemyFollowUpQuestionRepository(
    SqlAlchemyRepository[FollowUpQuestion, models.FollowUpQuestion, FollowUpQuestionFilter]
):
    model = models.FollowUpQuestion
    id_column = models.FollowUpQuestion.id
    created_column = models.FollowUpQuestion.created_at
    owner_column: ClassVar[InstrumentedAttribute[uuid.UUID] | None] = (
        models.FollowUpQuestion.owner_id
    )
    noun = "question"

    def to_entity(self, row: models.FollowUpQuestion) -> FollowUpQuestion:
        return mappers.question(row)

    def to_row(self, entity: FollowUpQuestion) -> models.FollowUpQuestion:
        return mappers.question_row(entity)

    def apply(self, row: models.FollowUpQuestion, entity: FollowUpQuestion) -> None:
        mappers.apply_question(row, entity)

    def id_of(self, entity: FollowUpQuestion) -> uuid.UUID:
        return entity.id

    def conditions(self, filter: FollowUpQuestionFilter) -> list[ColumnElement[bool]]:
        question = models.FollowUpQuestion
        found: list[ColumnElement[bool]] = []
        if filter.is_answered is True:
            found.append(question.answered_at.is_not(None))
        if filter.is_answered is False:
            found.append(question.answered_at.is_(None))
        if filter.is_retired is True:
            found.append(question.retired_at.is_not(None))
        if filter.is_retired is False:
            found.append(question.retired_at.is_(None))
        return found


class SqlAlchemyQuestionRoundRepository(
    SqlAlchemyRepository[QuestionRound, models.QuestionRound, QuestionRoundFilter]
):
    model = models.QuestionRound
    id_column = models.QuestionRound.id
    created_column = models.QuestionRound.created_at
    owner_column: ClassVar[InstrumentedAttribute[uuid.UUID] | None] = models.QuestionRound.owner_id
    noun = "question round"

    def to_entity(self, row: models.QuestionRound) -> QuestionRound:
        return mappers.question_round(row)

    def to_row(self, entity: QuestionRound) -> models.QuestionRound:
        return mappers.question_round_row(entity)

    def apply(self, row: models.QuestionRound, entity: QuestionRound) -> None:
        mappers.apply_question_round(row, entity)

    def id_of(self, entity: QuestionRound) -> uuid.UUID:
        return entity.id

    def conditions(self, filter: QuestionRoundFilter) -> list[ColumnElement[bool]]:
        if filter.status is None:
            return []
        return [models.QuestionRound.status == str(filter.status)]


class SqlAlchemyRoleFitRepository(SqlAlchemyRepository[RoleFit, models.RoleFit, RoleFitFilter]):
    model = models.RoleFit
    id_column = models.RoleFit.id
    created_column = models.RoleFit.created_at
    owner_column: ClassVar[InstrumentedAttribute[uuid.UUID] | None] = models.RoleFit.owner_id
    noun = "fit"

    def to_entity(self, row: models.RoleFit) -> RoleFit:
        return mappers.fit(row)

    def to_row(self, entity: RoleFit) -> models.RoleFit:
        return mappers.fit_row(entity)

    def apply(self, row: models.RoleFit, entity: RoleFit) -> None:
        mappers.apply_fit(row, entity)

    def id_of(self, entity: RoleFit) -> uuid.UUID:
        return entity.id

    def conditions(self, filter: RoleFitFilter) -> list[ColumnElement[bool]]:
        fit = models.RoleFit
        found: list[ColumnElement[bool]] = []
        if filter.role_id is not None:
            found.append(fit.role_id == filter.role_id)
        if filter.private_posting_id is not None:
            found.append(fit.private_posting_id == filter.private_posting_id)
        if filter.assessment_id is not None:
            found.append(fit.assessment_id == filter.assessment_id)
        return found
