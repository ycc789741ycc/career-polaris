"""SQLAlchemy implementations of Target's repositories.

The six methods come from ``kernel.db.repository.SqlAlchemyRepository``. Every
table here is owner-zone, so every repository is bound to one owner.
Requirements have no creation time stored, so they sort by id.
"""

from __future__ import annotations

import uuid
from typing import ClassVar

from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.elements import ColumnElement

from advisor.target.domain import (
    OwnPostingFit,
    OwnPostingFitFilter,
    OwnPostingFitRepository,
    PostingEvaluation,
    PostingEvaluationFilter,
    PostingEvaluationRepository,
    PostingRequirement,
    PostingRequirementFilter,
    PostingRequirementFit,
    PostingRequirementFitFilter,
    PostingRequirementFitRepository,
    PostingRequirementRepository,
    PrivateJobPosting,
    PrivateJobPostingFilter,
    PrivateJobPostingRepository,
)
from advisor.target.infra import mappers, models
from kernel.db.repository import SqlAlchemyRepository


class SqlAlchemyPrivateJobPostingRepository(
    SqlAlchemyRepository[PrivateJobPosting, models.PrivateJobPosting, PrivateJobPostingFilter],
    PrivateJobPostingRepository,
):
    model = models.PrivateJobPosting
    id_column = models.PrivateJobPosting.id
    created_column = models.PrivateJobPosting.created_at
    owner_column: ClassVar[InstrumentedAttribute[uuid.UUID] | None] = (
        models.PrivateJobPosting.owner_id
    )
    noun = "posting"

    def to_entity(self, row: models.PrivateJobPosting) -> PrivateJobPosting:
        return mappers.posting(row)

    def to_row(self, entity: PrivateJobPosting) -> models.PrivateJobPosting:
        return mappers.posting_row(entity)

    def apply(self, row: models.PrivateJobPosting, entity: PrivateJobPosting) -> None:
        mappers.apply_posting(row, entity)

    def id_of(self, entity: PrivateJobPosting) -> uuid.UUID:
        return entity.id

    def conditions(self, filter: PrivateJobPostingFilter) -> list[ColumnElement[bool]]:
        return []


class SqlAlchemyPostingEvaluationRepository(
    SqlAlchemyRepository[PostingEvaluation, models.PostingEvaluation, PostingEvaluationFilter],
    PostingEvaluationRepository,
):
    model = models.PostingEvaluation
    id_column = models.PostingEvaluation.id
    created_column = models.PostingEvaluation.requested_at
    owner_column: ClassVar[InstrumentedAttribute[uuid.UUID] | None] = (
        models.PostingEvaluation.owner_id
    )
    noun = "posting evaluation"

    def to_entity(self, row: models.PostingEvaluation) -> PostingEvaluation:
        return mappers.evaluation(row)

    def to_row(self, entity: PostingEvaluation) -> models.PostingEvaluation:
        return mappers.evaluation_row(entity)

    def apply(self, row: models.PostingEvaluation, entity: PostingEvaluation) -> None:
        mappers.apply_evaluation(row, entity)

    def id_of(self, entity: PostingEvaluation) -> uuid.UUID:
        return entity.id

    def conditions(self, filter: PostingEvaluationFilter) -> list[ColumnElement[bool]]:
        if filter.private_job_posting_id is None:
            return []
        return [models.PostingEvaluation.private_job_posting_id == filter.private_job_posting_id]


class SqlAlchemyPostingRequirementRepository(
    SqlAlchemyRepository[PostingRequirement, models.PostingRequirement, PostingRequirementFilter],
    PostingRequirementRepository,
):
    model = models.PostingRequirement
    id_column = models.PostingRequirement.id
    created_column = models.PostingRequirement.id
    owner_column: ClassVar[InstrumentedAttribute[uuid.UUID] | None] = (
        models.PostingRequirement.owner_id
    )
    noun = "posting requirement"

    def to_entity(self, row: models.PostingRequirement) -> PostingRequirement:
        return mappers.requirement(row)

    def to_row(self, entity: PostingRequirement) -> models.PostingRequirement:
        return mappers.requirement_row(entity)

    def apply(self, row: models.PostingRequirement, entity: PostingRequirement) -> None:
        mappers.apply_requirement(row, entity)

    def id_of(self, entity: PostingRequirement) -> uuid.UUID:
        return entity.id

    def conditions(self, filter: PostingRequirementFilter) -> list[ColumnElement[bool]]:
        if filter.private_job_posting_id is None:
            return []
        return [models.PostingRequirement.private_job_posting_id == filter.private_job_posting_id]


class SqlAlchemyPostingRequirementFitRepository(
    SqlAlchemyRepository[
        PostingRequirementFit, models.PostingRequirementFit, PostingRequirementFitFilter
    ],
    PostingRequirementFitRepository,
):
    model = models.PostingRequirementFit
    id_column = models.PostingRequirementFit.id
    created_column = models.PostingRequirementFit.created_at
    owner_column: ClassVar[InstrumentedAttribute[uuid.UUID] | None] = (
        models.PostingRequirementFit.owner_id
    )
    noun = "posting requirement fit"

    def to_entity(self, row: models.PostingRequirementFit) -> PostingRequirementFit:
        return mappers.requirement_fit(row)

    def to_row(self, entity: PostingRequirementFit) -> models.PostingRequirementFit:
        return mappers.requirement_fit_row(entity)

    def apply(self, row: models.PostingRequirementFit, entity: PostingRequirementFit) -> None:
        mappers.apply_requirement_fit(row, entity)

    def id_of(self, entity: PostingRequirementFit) -> uuid.UUID:
        return entity.id

    def conditions(self, filter: PostingRequirementFitFilter) -> list[ColumnElement[bool]]:
        if filter.private_job_posting_id is None:
            return []
        return [
            models.PostingRequirementFit.private_job_posting_id == filter.private_job_posting_id
        ]


class SqlAlchemyOwnPostingFitRepository(
    SqlAlchemyRepository[OwnPostingFit, models.OwnPostingFit, OwnPostingFitFilter],
    OwnPostingFitRepository,
):
    model = models.OwnPostingFit
    id_column = models.OwnPostingFit.id
    created_column = models.OwnPostingFit.created_at
    owner_column: ClassVar[InstrumentedAttribute[uuid.UUID] | None] = models.OwnPostingFit.owner_id
    noun = "posting fit"

    def to_entity(self, row: models.OwnPostingFit) -> OwnPostingFit:
        return mappers.fit(row)

    def to_row(self, entity: OwnPostingFit) -> models.OwnPostingFit:
        return mappers.fit_row(entity)

    def apply(self, row: models.OwnPostingFit, entity: OwnPostingFit) -> None:
        mappers.apply_fit(row, entity)

    def id_of(self, entity: OwnPostingFit) -> uuid.UUID:
        return entity.id

    def conditions(self, filter: OwnPostingFitFilter) -> list[ColumnElement[bool]]:
        if filter.private_job_posting_ids is None:
            return []
        return [models.OwnPostingFit.private_job_posting_id.in_(filter.private_job_posting_ids)]
