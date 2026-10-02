"""ORM rows to Target's entities and back. No rules live here, only shape."""

from __future__ import annotations

from advisor.target.domain import (
    OwnPostingFit,
    PostingEvaluation,
    PostingEvaluationStatus,
    PostingRequirement,
    PostingRequirementFit,
    PrivateJobPosting,
)
from advisor.target.infra import models


def posting(row: models.PrivateJobPosting) -> PrivateJobPosting:
    return PrivateJobPosting(
        id=row.id,
        owner_id=row.owner_id,
        title=row.title,
        company_name=row.company_name,
        job_description=row.job_description,
        created_at=row.created_at,
    )


def posting_row(entity: PrivateJobPosting) -> models.PrivateJobPosting:
    row = models.PrivateJobPosting(id=entity.id, owner_id=entity.owner_id)
    apply_posting(row, entity)
    return row


def apply_posting(row: models.PrivateJobPosting, entity: PrivateJobPosting) -> None:
    row.title = entity.title
    row.company_name = entity.company_name
    row.job_description = entity.job_description


def evaluation(row: models.PostingEvaluation) -> PostingEvaluation:
    return PostingEvaluation(
        id=row.id,
        owner_id=row.owner_id,
        private_job_posting_id=row.private_job_posting_id,
        status=PostingEvaluationStatus(row.status),
        reads_requirements=row.reads_requirements,
        requested_at=row.requested_at,
        finished_at=row.finished_at,
        error_code=row.error_code,
        error_message=row.error_message,
    )


def evaluation_row(entity: PostingEvaluation) -> models.PostingEvaluation:
    row = models.PostingEvaluation(id=entity.id, owner_id=entity.owner_id)
    apply_evaluation(row, entity)
    return row


def apply_evaluation(row: models.PostingEvaluation, entity: PostingEvaluation) -> None:
    row.private_job_posting_id = entity.private_job_posting_id
    row.status = str(entity.status)
    row.reads_requirements = entity.reads_requirements
    row.requested_at = entity.requested_at
    row.finished_at = entity.finished_at
    row.error_code = entity.error_code
    row.error_message = entity.error_message


def requirement(row: models.PostingRequirement) -> PostingRequirement:
    return PostingRequirement(
        id=row.id,
        owner_id=row.owner_id,
        private_job_posting_id=row.private_job_posting_id,
        statement=row.statement,
        weight=row.weight,
        expected_level=row.expected_level,
    )


def requirement_row(entity: PostingRequirement) -> models.PostingRequirement:
    row = models.PostingRequirement(id=entity.id, owner_id=entity.owner_id)
    apply_requirement(row, entity)
    return row


def apply_requirement(row: models.PostingRequirement, entity: PostingRequirement) -> None:
    row.private_job_posting_id = entity.private_job_posting_id
    row.statement = entity.statement
    row.weight = entity.weight
    row.expected_level = entity.expected_level


def requirement_fit(row: models.PostingRequirementFit) -> PostingRequirementFit:
    return PostingRequirementFit(
        id=row.id,
        owner_id=row.owner_id,
        private_job_posting_id=row.private_job_posting_id,
        assessment_id=row.assessment_id,
        requirements=tuple(row.requirements),
        requirement_map=dict(row.requirement_map),
        target_profile=dict(row.target_profile),
        reasoning=row.reasoning,
        model_id=row.model_id,
        template_version=row.template_version,
        requirements_digest=row.requirements_digest,
        created_at=row.created_at,
    )


def requirement_fit_row(entity: PostingRequirementFit) -> models.PostingRequirementFit:
    row = models.PostingRequirementFit(id=entity.id, owner_id=entity.owner_id)
    apply_requirement_fit(row, entity)
    return row


def apply_requirement_fit(row: models.PostingRequirementFit, entity: PostingRequirementFit) -> None:
    row.private_job_posting_id = entity.private_job_posting_id
    row.assessment_id = entity.assessment_id
    row.requirements = list(entity.requirements)
    row.requirement_map = dict(entity.requirement_map)
    row.target_profile = dict(entity.target_profile)
    row.reasoning = entity.reasoning
    row.model_id = entity.model_id
    row.template_version = entity.template_version
    row.requirements_digest = entity.requirements_digest


def fit(row: models.OwnPostingFit) -> OwnPostingFit:
    return OwnPostingFit(
        id=row.id,
        owner_id=row.owner_id,
        private_job_posting_id=row.private_job_posting_id,
        source_fit_id=row.source_fit_id,
        assessment_id=row.assessment_id,
        score=row.score,
        requirements=tuple(row.requirements),
        requirement_map=dict(row.requirement_map),
        target_profile=dict(row.target_profile),
        gaps=tuple(row.gaps),
        uncovered=tuple(row.uncovered),
        created_at=row.created_at,
    )


def fit_row(entity: OwnPostingFit) -> models.OwnPostingFit:
    row = models.OwnPostingFit(id=entity.id, owner_id=entity.owner_id)
    apply_fit(row, entity)
    return row


def apply_fit(row: models.OwnPostingFit, entity: OwnPostingFit) -> None:
    row.private_job_posting_id = entity.private_job_posting_id
    row.source_fit_id = entity.source_fit_id
    row.assessment_id = entity.assessment_id
    row.score = entity.score
    row.requirements = list(entity.requirements)
    row.requirement_map = dict(entity.requirement_map)
    row.target_profile = dict(entity.target_profile)
    row.gaps = list(entity.gaps)
    row.uncovered = list(entity.uncovered)
