"""Builds the assessment component from the infrastructure handles it is given.

The composition root calls this; nothing else constructs a repository or a
unit of work (ADR 0011).
"""

from __future__ import annotations

from advisor.assessment.infra.unit_of_work import SqlAlchemyAssessmentUnitOfWork
from advisor.assessment.service import AssessmentService
from advisor.profile import ProfileService
from advisor.rolemap import RoleMapService
from kernel.ai_gateway import AiGateway
from kernel.db import Database


def create_assessment_service(
    database: Database,
    *,
    profile: ProfileService,
    rolemap: RoleMapService,
    gateway: AiGateway,
    confidence_threshold: float,
) -> AssessmentService:
    return AssessmentService(
        SqlAlchemyAssessmentUnitOfWork(database),
        profile=profile,
        rolemap=rolemap,
        gateway=gateway,
        confidence_threshold=confidence_threshold,
    )
