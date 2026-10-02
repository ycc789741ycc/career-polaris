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
from kernel.storage import ObjectStore


def create_target_service(
    database: Database,
    *,
    assessment: AssessmentService,
    rolemap: RoleMapService,
    object_store: ObjectStore,
    upload_max_bytes: int,
    upload_max_pages: int,
) -> TargetService:
    return TargetService(
        SqlAlchemyTargetUnitOfWork(database),
        assessment=assessment,
        rolemap=rolemap,
        object_store=object_store,
        upload_max_bytes=upload_max_bytes,
        upload_max_pages=upload_max_pages,
    )
