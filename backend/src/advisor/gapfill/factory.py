"""Builds the Fill the gap component from the infrastructure handles it is given.

The composition root calls this; nothing else constructs a repository or a
unit of work (ADR 0011).
"""

from __future__ import annotations

from advisor.gapfill.infra.unit_of_work import SqlAlchemyGapFillUnitOfWork
from advisor.gapfill.service import GapFillService
from advisor.profile import ProfileService
from advisor.target import TargetService
from kernel.ai_gateway import AiGateway
from kernel.db import Database


def create_gapfill_service(
    database: Database,
    *,
    target: TargetService,
    profile: ProfileService,
    gateway: AiGateway,
) -> GapFillService:
    return GapFillService(
        SqlAlchemyGapFillUnitOfWork(database), target=target, profile=profile, gateway=gateway
    )
