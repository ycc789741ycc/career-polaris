"""Builds the gap-plan component from the infrastructure handles it is given.

The composition root calls this; nothing else constructs a repository or a
unit of work (ADR 0011).
"""

from __future__ import annotations

from advisor.assessment import AssessmentService
from advisor.gapfill import GapFillService
from advisor.gapplan.infra.unit_of_work import SqlAlchemyGapPlanUnitOfWork
from advisor.gapplan.service import GapPlanService
from advisor.profile import ProfileService
from advisor.rolemap import RoleMapService
from advisor.target import TargetService
from kernel.ai_gateway import AiGateway
from kernel.db import Database


def create_gapplan_service(
    database: Database,
    *,
    target: TargetService,
    profile: ProfileService,
    assessment: AssessmentService,
    rolemap: RoleMapService,
    gapfill: GapFillService,
    gateway: AiGateway,
) -> GapPlanService:
    return GapPlanService(
        SqlAlchemyGapPlanUnitOfWork(database),
        target=target,
        profile=profile,
        assessment=assessment,
        rolemap=rolemap,
        gapfill=gapfill,
        gateway=gateway,
    )
