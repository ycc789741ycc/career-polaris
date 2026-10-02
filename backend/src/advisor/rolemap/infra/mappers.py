"""ORM rows to role-map entities and back. No rules live here, only shape."""

from __future__ import annotations

import uuid

from advisor.rolemap.domain import (
    BuildRun,
    BuildRunStatus,
    CandidateStrength,
    LineageEntry,
    PostingEvaluation,
    PostingEvaluationStatus,
    PostingFit,
    PostingFitBasis,
    PostingRequirement,
    PostingRequirementFit,
    Role,
    RoleCandidate,
    RoleChange,
    RoleFit,
    RoleMember,
    RoleRequirement,
)
from advisor.rolemap.infra import models


def role(row: models.Role) -> Role:
    return Role(
        id=row.id,
        owner_id=row.owner_id,
        name=row.name,
        is_coherent=row.is_coherent,
        opening_count=row.opening_count,
        hiring_bar=row.hiring_bar,
        bar_confidence=row.bar_confidence,
        bar_basis=row.bar_basis,
        bar_sample_size=row.bar_sample_size,
        bar_reasoning=row.bar_reasoning,
        salary_bands=dict(row.salary_bands or {}),
        model_id=row.model_id,
        template_version=row.template_version,
        retired_at=row.retired_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def role_row(entity: Role) -> models.Role:
    row = models.Role(id=entity.id, owner_id=entity.owner_id)
    apply_role(row, entity)
    return row


def apply_role(row: models.Role, entity: Role) -> None:
    row.name = entity.name
    row.is_coherent = entity.is_coherent
    row.opening_count = entity.opening_count
    row.hiring_bar = entity.hiring_bar
    row.bar_confidence = entity.bar_confidence
    row.bar_basis = entity.bar_basis
    row.bar_sample_size = entity.bar_sample_size
    row.bar_reasoning = entity.bar_reasoning
    row.salary_bands = dict(entity.salary_bands)
    row.model_id = entity.model_id
    row.template_version = entity.template_version
    row.retired_at = entity.retired_at


def member(row: models.RoleMember) -> RoleMember:
    return RoleMember(
        id=row.id, owner_id=row.owner_id, role_id=row.role_id, posting_key=row.posting_key
    )


def member_row(entity: RoleMember) -> models.RoleMember:
    return models.RoleMember(
        id=entity.id,
        owner_id=entity.owner_id,
        role_id=entity.role_id,
        posting_key=entity.posting_key,
    )


def apply_member(row: models.RoleMember, entity: RoleMember) -> None:
    row.role_id = entity.role_id
    row.posting_key = entity.posting_key


def requirement(row: models.RoleRequirement) -> RoleRequirement:
    return RoleRequirement(
        id=row.id,
        owner_id=row.owner_id,
        role_id=row.role_id,
        statement=row.statement,
        weight=row.weight,
        expected_level=row.expected_level,
    )


def requirement_row(entity: RoleRequirement) -> models.RoleRequirement:
    row = models.RoleRequirement(id=entity.id, owner_id=entity.owner_id, role_id=entity.role_id)
    apply_requirement(row, entity)
    return row


def apply_requirement(row: models.RoleRequirement, entity: RoleRequirement) -> None:
    row.statement = entity.statement
    row.weight = entity.weight
    row.expected_level = entity.expected_level


def lineage(row: models.RoleLineage) -> LineageEntry:
    return LineageEntry(
        id=row.id,
        owner_id=row.owner_id,
        role_id=row.role_id,
        kind=RoleChange(row.kind),
        from_role_ids=tuple(row.from_role_ids),
        recorded_at=row.recorded_at,
    )


def lineage_row(entity: LineageEntry) -> models.RoleLineage:
    row = models.RoleLineage(id=entity.id, owner_id=entity.owner_id)
    apply_lineage(row, entity)
    return row


def apply_lineage(row: models.RoleLineage, entity: LineageEntry) -> None:
    row.role_id = entity.role_id
    row.kind = str(entity.kind)
    row.from_role_ids = list(entity.from_role_ids)


def build_run(row: models.BuildRun) -> BuildRun:
    return BuildRun(
        id=row.id,
        owner_id=row.owner_id,
        status=BuildRunStatus(row.status),
        requested_at=row.requested_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
        error_code=row.error_code,
        error_message=row.error_message,
        needed_source_ids=tuple(uuid.UUID(i) for i in row.needed_source_ids or ()),
        awaited_source_ids=tuple(uuid.UUID(i) for i in row.awaited_source_ids or ()),
        locations=tuple(row.locations or ()),
        awaited_since=row.awaited_since,
        market_data_at=row.market_data_at,
    )


def build_run_row(entity: BuildRun) -> models.BuildRun:
    row = models.BuildRun(id=entity.id, owner_id=entity.owner_id, requested_at=entity.requested_at)
    apply_build_run(row, entity)
    return row


def apply_build_run(row: models.BuildRun, entity: BuildRun) -> None:
    row.status = str(entity.status)
    row.started_at = entity.started_at
    row.finished_at = entity.finished_at
    row.error_code = entity.error_code
    row.error_message = entity.error_message
    row.needed_source_ids = [str(i) for i in entity.needed_source_ids]
    row.awaited_source_ids = [str(i) for i in entity.awaited_source_ids]
    row.locations = list(entity.locations)
    row.awaited_since = entity.awaited_since
    row.market_data_at = entity.market_data_at


def candidate(row: models.RoleCandidate) -> RoleCandidate:
    return RoleCandidate(
        id=row.id,
        owner_id=row.owner_id,
        assessment_id=row.assessment_id,
        rank=row.rank,
        title=row.title,
        description=row.description,
        dimension_keys=tuple(row.dimension_keys),
        role_id=row.role_id,
        opening_count=row.opening_count,
        fit_estimate=row.fit_estimate,
        created_at=row.created_at,
    )


def candidate_row(entity: RoleCandidate) -> models.RoleCandidate:
    row = models.RoleCandidate(
        id=entity.id, owner_id=entity.owner_id, assessment_id=entity.assessment_id
    )
    apply_candidate(row, entity)
    return row


def apply_candidate(row: models.RoleCandidate, entity: RoleCandidate) -> None:
    row.rank = entity.rank
    row.title = entity.title
    row.description = entity.description
    row.dimension_keys = list(entity.dimension_keys)
    row.role_id = entity.role_id
    row.opening_count = entity.opening_count
    row.fit_estimate = entity.fit_estimate


def strength(row: models.CandidateStrength) -> CandidateStrength:
    return CandidateStrength(
        id=row.id,
        owner_id=row.owner_id,
        assessment_id=row.assessment_id,
        dimension_key=row.dimension_key,
        name=row.name,
        read=row.read,
        weight=row.weight,
        score=row.score,
        confidence=row.confidence,
    )


def strength_row(entity: CandidateStrength) -> models.CandidateStrength:
    row = models.CandidateStrength(
        id=entity.id, owner_id=entity.owner_id, assessment_id=entity.assessment_id
    )
    apply_strength(row, entity)
    return row


def apply_strength(row: models.CandidateStrength, entity: CandidateStrength) -> None:
    row.dimension_key = entity.dimension_key
    row.name = entity.name
    row.read = entity.read
    row.weight = entity.weight
    row.score = entity.score
    row.confidence = entity.confidence


def fit(row: models.RoleFit) -> RoleFit:
    return RoleFit(
        id=row.id,
        owner_id=row.owner_id,
        assessment_id=row.assessment_id,
        role_id=row.role_id,
        score=row.score,
        reasoning=row.reasoning,
        target_profile=dict(row.target_profile),
        gaps=tuple(row.gaps),
        uncovered=tuple(row.uncovered),
        model_id=row.model_id,
        template_version=row.template_version,
        requirements=tuple(row.requirements or []),
        requirement_map=dict(row.requirement_map or {}),
        created_at=row.created_at,
    )


def fit_row(entity: RoleFit) -> models.RoleFit:
    row = models.RoleFit(id=entity.id, owner_id=entity.owner_id)
    apply_fit(row, entity)
    return row


def apply_fit(row: models.RoleFit, entity: RoleFit) -> None:
    row.assessment_id = entity.assessment_id
    row.role_id = entity.role_id
    row.score = entity.score
    row.reasoning = entity.reasoning
    row.target_profile = dict(entity.target_profile)
    row.gaps = list(entity.gaps)
    row.uncovered = list(entity.uncovered)
    row.requirements = list(entity.requirements)
    row.requirement_map = dict(entity.requirement_map)
    row.model_id = entity.model_id
    row.template_version = entity.template_version


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


def posting_requirement(row: models.PostingRequirement) -> PostingRequirement:
    return PostingRequirement(
        id=row.id,
        owner_id=row.owner_id,
        private_job_posting_id=row.private_job_posting_id,
        statement=row.statement,
        weight=row.weight,
        expected_level=row.expected_level,
    )


def posting_requirement_row(entity: PostingRequirement) -> models.PostingRequirement:
    row = models.PostingRequirement(id=entity.id, owner_id=entity.owner_id)
    apply_posting_requirement(row, entity)
    return row


def apply_posting_requirement(row: models.PostingRequirement, entity: PostingRequirement) -> None:
    row.private_job_posting_id = entity.private_job_posting_id
    row.statement = entity.statement
    row.weight = entity.weight
    row.expected_level = entity.expected_level


def posting_requirement_fit(row: models.PostingRequirementFit) -> PostingRequirementFit:
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
        created_at=row.created_at,
    )


def posting_requirement_fit_row(entity: PostingRequirementFit) -> models.PostingRequirementFit:
    row = models.PostingRequirementFit(id=entity.id, owner_id=entity.owner_id)
    apply_posting_requirement_fit(row, entity)
    return row


def apply_posting_requirement_fit(
    row: models.PostingRequirementFit, entity: PostingRequirementFit
) -> None:
    row.private_job_posting_id = entity.private_job_posting_id
    row.assessment_id = entity.assessment_id
    row.requirements = list(entity.requirements)
    row.requirement_map = dict(entity.requirement_map)
    row.target_profile = dict(entity.target_profile)
    row.reasoning = entity.reasoning
    row.model_id = entity.model_id
    row.template_version = entity.template_version


def posting_fit(row: models.PostingFit) -> PostingFit:
    return PostingFit(
        id=row.id,
        owner_id=row.owner_id,
        posting_key=row.posting_key,
        basis=PostingFitBasis(row.basis),
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


def posting_fit_row(entity: PostingFit) -> models.PostingFit:
    row = models.PostingFit(id=entity.id, owner_id=entity.owner_id)
    apply_posting_fit(row, entity)
    return row


def apply_posting_fit(row: models.PostingFit, entity: PostingFit) -> None:
    row.posting_key = entity.posting_key
    row.basis = str(entity.basis)
    row.source_fit_id = entity.source_fit_id
    row.assessment_id = entity.assessment_id
    row.score = entity.score
    row.requirements = list(entity.requirements)
    row.requirement_map = dict(entity.requirement_map)
    row.target_profile = dict(entity.target_profile)
    row.gaps = list(entity.gaps)
    row.uncovered = list(entity.uncovered)
