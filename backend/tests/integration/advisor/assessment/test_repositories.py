"""The SQLAlchemy side of assessment's repositories, against a real database.

Worth proving here: snapshots survive their mappers (JSON included), the
answered and retired filters and newest-first order hold, an owner sees nobody
else's rows, and each event lands in the outbox as the dispatcher reads it.
"""

from __future__ import annotations

import uuid

import pytest

from advisor.assessment.domain import (
    AssessedScore,
    AssessedScoreFilter,
    RoleFit,
    RoleFitFilter,
    SkillAssessment,
    SkillAssessmentFilter,
)
from advisor.assessment.infra.unit_of_work import SqlAlchemyAssessmentUnitOfWork
from kernel.db import Database

pytestmark = pytest.mark.integration


async def test_assessment_snapshots_round_trip(
    database: Database, account: uuid.UUID, other_account: uuid.UUID
) -> None:
    uow = SqlAlchemyAssessmentUnitOfWork(database)
    async with uow.for_owner(account) as mine:
        assessment = await mine.assessments.create(
            SkillAssessment(
                id=uuid.uuid4(),
                owner_id=account,
                profile_version=3,
                model_id="m",
                template_version="v1",
            )
        )
        score = await mine.scores.create(
            AssessedScore(
                id=uuid.uuid4(),
                owner_id=account,
                assessment_id=assessment.id,
                dimension_key="api",
                score=72,
                confidence=0.8,
                read="Strong",
                evidence_ids=("e1", "e2"),
            )
        )
        fit = await mine.fits.create(
            RoleFit(
                id=uuid.uuid4(),
                owner_id=account,
                assessment_id=assessment.id,
                role_id=uuid.uuid4(),
                private_posting_id=None,
                score=64,
                reasoning="close",
                target_profile={"api": 80},
                gaps=({"dimension_key": "api", "user_score": 72, "target_score": 80, "delta": -8},),
                uncovered=({"statement": "Kafka", "weight": 0.5},),
                model_id="m",
                template_version="v1",
                requirements=({"statement": "APIs", "weight": 0.9, "expected_level": "expert"},),
                requirement_map={"APIs": "api"},
            )
        )
    assert assessment.created_at is not None and fit.created_at is not None

    async with uow.for_owner(account) as mine:
        assert await mine.assessments.get_list(SkillAssessmentFilter(), page_size=1) == [assessment]
        assert await mine.scores.get_list(AssessedScoreFilter(assessment_id=assessment.id)) == [
            score
        ]
        assert await mine.fits.get_list(RoleFitFilter(role_id=fit.role_id)) == [fit]

    async with uow.for_owner(other_account) as theirs:
        assert await theirs.fits.get(fit.id) is None
        assert await theirs.assessments.get_count(SkillAssessmentFilter()) == 0
