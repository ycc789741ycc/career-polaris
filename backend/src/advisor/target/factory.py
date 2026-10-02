"""Builds the target component from the infrastructure handles it is given.

The composition root calls this; nothing else constructs a repository or a
unit of work (ADR 0011).
"""

from __future__ import annotations

from advisor.assessment import AssessmentService
from advisor.rolemap import RoleMapService
from advisor.target.infra.unit_of_work import SqlAlchemyTargetUnitOfWork
from advisor.target.service import TargetService
from kernel.db import Database


def create_target_service(
    database: Database, *, assessment: AssessmentService, rolemap: RoleMapService
) -> TargetService:
    return TargetService(
        SqlAlchemyTargetUnitOfWork(database), assessment=assessment, rolemap=rolemap
    )
