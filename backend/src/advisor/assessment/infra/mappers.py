"""ORM rows to assessment entities and back. No rules live here, only shape."""

from __future__ import annotations

from advisor.assessment.domain import (
    AssessedScore,
    DimensionChange,
    FollowUpQuestion,
    LineageKind,
    RoleFit,
    SkillAssessment,
    SkillDimension,
)
from advisor.assessment.infra import models


def dimension(row: models.SkillDimension) -> SkillDimension:
    return SkillDimension(
        id=row.id,
        owner_id=row.owner_id,
        key=row.key,
        name=row.name,
        short_name=row.short_name,
        retired_at=row.retired_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def dimension_row(entity: SkillDimension) -> models.SkillDimension:
    row = models.SkillDimension(id=entity.id, owner_id=entity.owner_id, key=entity.key)
    apply_dimension(row, entity)
    return row


def apply_dimension(row: models.SkillDimension, entity: SkillDimension) -> None:
    row.name = entity.name
    row.short_name = entity.short_name
    row.retired_at = entity.retired_at


def assessment(row: models.SkillAssessment) -> SkillAssessment:
    return SkillAssessment(
        id=row.id,
        owner_id=row.owner_id,
        profile_version=row.profile_version,
        model_id=row.model_id,
        template_version=row.template_version,
        created_at=row.created_at,
    )


def assessment_row(entity: SkillAssessment) -> models.SkillAssessment:
    row = models.SkillAssessment(id=entity.id, owner_id=entity.owner_id)
    apply_assessment(row, entity)
    return row


def apply_assessment(row: models.SkillAssessment, entity: SkillAssessment) -> None:
    row.profile_version = entity.profile_version
    row.model_id = entity.model_id
    row.template_version = entity.template_version


def score(row: models.DimensionScore) -> AssessedScore:
    return AssessedScore(
        id=row.id,
        owner_id=row.owner_id,
        assessment_id=row.assessment_id,
        dimension_key=row.dimension_key,
        score=row.score,
        confidence=row.confidence,
        read=row.read,
        evidence_ids=tuple(row.evidence_ids),
    )


def score_row(entity: AssessedScore) -> models.DimensionScore:
    row = models.DimensionScore(
        id=entity.id, owner_id=entity.owner_id, assessment_id=entity.assessment_id
    )
    apply_score(row, entity)
    return row


def apply_score(row: models.DimensionScore, entity: AssessedScore) -> None:
    row.dimension_key = entity.dimension_key
    row.score = entity.score
    row.confidence = entity.confidence
    row.read = entity.read
    row.evidence_ids = list(entity.evidence_ids)


def change(row: models.DimensionLineage) -> DimensionChange:
    return DimensionChange(
        id=row.id,
        owner_id=row.owner_id,
        assessment_id=row.assessment_id,
        kind=LineageKind(row.kind),
        dimension_key=row.dimension_key,
        from_keys=tuple(row.from_keys),
        previous_name=row.previous_name,
        recorded_at=row.recorded_at,
    )


def change_row(entity: DimensionChange) -> models.DimensionLineage:
    row = models.DimensionLineage(
        id=entity.id, owner_id=entity.owner_id, assessment_id=entity.assessment_id
    )
    apply_change(row, entity)
    return row


def apply_change(row: models.DimensionLineage, entity: DimensionChange) -> None:
    row.kind = str(entity.kind)
    row.dimension_key = entity.dimension_key
    row.from_keys = list(entity.from_keys)
    row.previous_name = entity.previous_name


def question(row: models.FollowUpQuestion) -> FollowUpQuestion:
    return FollowUpQuestion(
        id=row.id,
        owner_id=row.owner_id,
        assessment_id=row.assessment_id,
        dimension_key=row.dimension_key,
        text=row.text,
        why=row.why,
        options=tuple(row.options),
        answer=row.answer,
        answered_at=row.answered_at,
        created_at=row.created_at,
    )


def question_row(entity: FollowUpQuestion) -> models.FollowUpQuestion:
    row = models.FollowUpQuestion(
        id=entity.id, owner_id=entity.owner_id, assessment_id=entity.assessment_id
    )
    apply_question(row, entity)
    return row


def apply_question(row: models.FollowUpQuestion, entity: FollowUpQuestion) -> None:
    row.dimension_key = entity.dimension_key
    row.text = entity.text
    row.why = entity.why
    row.options = list(entity.options)
    row.answer = entity.answer
    row.answered_at = entity.answered_at


def fit(row: models.RoleFit) -> RoleFit:
    return RoleFit(
        id=row.id,
        owner_id=row.owner_id,
        assessment_id=row.assessment_id,
        role_id=row.role_id,
        private_posting_id=row.private_posting_id,
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
    row.private_posting_id = entity.private_posting_id
    row.score = entity.score
    row.reasoning = entity.reasoning
    row.target_profile = dict(entity.target_profile)
    row.gaps = list(entity.gaps)
    row.uncovered = list(entity.uncovered)
    row.requirements = list(entity.requirements)
    row.requirement_map = dict(entity.requirement_map)
    row.model_id = entity.model_id
    row.template_version = entity.template_version
