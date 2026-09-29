"""SQLAlchemy implementations of Fill the gap's repositories.

The six methods come from ``kernel.db.repository.SqlAlchemyRepository``. Every
table here is owner-zone, so every repository is bound to one owner. Questions
have no creation time stored, so they sort by id.
"""

from __future__ import annotations

import uuid
from typing import ClassVar

from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.elements import ColumnElement

from advisor.gapfill.domain import (
    GapQuestion,
    GapQuestionFilter,
    QuestionSet,
    QuestionSetFilter,
)
from advisor.gapfill.infra import mappers, models
from kernel.db.repository import SqlAlchemyRepository


class SqlAlchemyQuestionSetRepository(
    SqlAlchemyRepository[QuestionSet, models.QuestionSet, QuestionSetFilter]
):
    model = models.QuestionSet
    id_column = models.QuestionSet.id
    created_column = models.QuestionSet.created_at
    owner_column: ClassVar[InstrumentedAttribute[uuid.UUID] | None] = models.QuestionSet.owner_id
    noun = "question set"

    def to_entity(self, row: models.QuestionSet) -> QuestionSet:
        return mappers.question_set(row)

    def to_row(self, entity: QuestionSet) -> models.QuestionSet:
        return mappers.question_set_row(entity)

    def apply(self, row: models.QuestionSet, entity: QuestionSet) -> None:
        mappers.apply_question_set(row, entity)

    def id_of(self, entity: QuestionSet) -> uuid.UUID:
        return entity.id

    def conditions(self, filter: QuestionSetFilter) -> list[ColumnElement[bool]]:
        sets = models.QuestionSet
        found: list[ColumnElement[bool]] = []
        if filter.role_id is not None:
            found.append(sets.role_id == filter.role_id)
        if filter.job_posting_id is not None:
            found.append(sets.job_posting_id == filter.job_posting_id)
        elif filter.role_only:
            found.append(sets.job_posting_id.is_(None))
        if filter.statuses is not None:
            found.append(sets.status.in_([str(s) for s in filter.statuses]))
        return found


class SqlAlchemyGapQuestionRepository(
    SqlAlchemyRepository[GapQuestion, models.Question, GapQuestionFilter]
):
    model = models.Question
    id_column = models.Question.id
    created_column = models.Question.id
    owner_column: ClassVar[InstrumentedAttribute[uuid.UUID] | None] = models.Question.owner_id
    noun = "question"

    def to_entity(self, row: models.Question) -> GapQuestion:
        return mappers.question(row)

    def to_row(self, entity: GapQuestion) -> models.Question:
        return mappers.question_row(entity)

    def apply(self, row: models.Question, entity: GapQuestion) -> None:
        mappers.apply_question(row, entity)

    def id_of(self, entity: GapQuestion) -> uuid.UUID:
        return entity.id

    def conditions(self, filter: GapQuestionFilter) -> list[ColumnElement[bool]]:
        if filter.set_ids is None:
            return []
        return [models.Question.set_id.in_(filter.set_ids)]
