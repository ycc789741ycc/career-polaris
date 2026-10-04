"""Builds the Resume Advisor from the infrastructure handles it is given.

The composition root calls this; nothing else constructs a repository or a
unit of work (ADR 0011).
"""

from __future__ import annotations

from advisor.assessment import AssessmentService
from advisor.gapfill import GapFillService
from advisor.profile import ProfileService
from advisor.resume.infra.unit_of_work import SqlAlchemyResumeUnitOfWork
from advisor.resume.service import ResumeService
from advisor.target import TargetService
from kernel.ai_gateway import AiGateway
from kernel.db import Database
from kernel.storage import ObjectStore


def create_resume_service(
    database: Database,
    *,
    target: TargetService,
    profile: ProfileService,
    assessment: AssessmentService,
    gapfill: GapFillService,
    gateway: AiGateway,
    object_store: ObjectStore,
    template_max: int,
    template_upload_max_bytes: int = 5_242_880,
    template_upload_max_pages: int = 3,
) -> ResumeService:
    return ResumeService(
        SqlAlchemyResumeUnitOfWork(database),
        target=target,
        profile=profile,
        assessment=assessment,
        gapfill=gapfill,
        gateway=gateway,
        object_store=object_store,
        template_max=template_max,
        template_upload_max_bytes=template_upload_max_bytes,
        template_upload_max_pages=template_upload_max_pages,
    )
