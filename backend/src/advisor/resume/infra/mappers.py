"""ORM rows to Resume Advisor entities and back. No rules live here, only shape.

A résumé's Target is a role and an optional opening, as two columns.
"""

from __future__ import annotations

from typing import Any

from advisor.resume.domain import (
    Export,
    ExportStatus,
    Options,
    ResumeStatus,
    ResumeVersion,
    Revision,
    TailoredResume,
    Template,
    VersionSource,
)
from advisor.resume.infra import models


def options_of(data: dict[str, Any]) -> Options:
    return Options(
        metrics=bool(data.get("metrics", True)),
        reorder=bool(data.get("reorder", True)),
        trim=bool(data.get("trim", False)),
    )


def options_dict(options: Options) -> dict[str, bool]:
    return {"metrics": options.metrics, "reorder": options.reorder, "trim": options.trim}


def resume(row: models.Resume) -> TailoredResume:
    return TailoredResume(
        id=row.id,
        owner_id=row.owner_id,
        role_id=row.role_id,
        job_posting_id=row.job_posting_id,
        private_job_posting_id=row.private_job_posting_id,
        target_label=row.target_label,
        template=Template(row.template),
        options=options_of(row.options),
        status=ResumeStatus(row.status),
        created_at=row.created_at,
        updated_at=row.updated_at,
        snapshot=dict(row.snapshot) if row.snapshot is not None else None,
        coverage=tuple(row.coverage),
        error_code=row.error_code,
        error_message=row.error_message,
    )


def resume_row(entity: TailoredResume) -> models.Resume:
    row = models.Resume(
        id=entity.id,
        owner_id=entity.owner_id,
        role_id=entity.role_id,
        job_posting_id=entity.job_posting_id,
        private_job_posting_id=entity.private_job_posting_id,
        created_at=entity.created_at,
    )
    apply_resume(row, entity)
    return row


def apply_resume(row: models.Resume, entity: TailoredResume) -> None:
    row.target_label = entity.target_label
    row.template = str(entity.template)
    row.options = options_dict(entity.options)
    row.status = str(entity.status)
    row.snapshot = entity.snapshot
    row.coverage = list(entity.coverage)
    row.error_code = entity.error_code
    row.error_message = entity.error_message
    row.updated_at = entity.updated_at


def version(row: models.ResumeVersion) -> ResumeVersion:
    return ResumeVersion(
        id=row.id,
        owner_id=row.owner_id,
        resume_id=row.resume_id,
        number=row.number,
        label=row.label,
        content=dict(row.content),
        source=VersionSource(row.source),
        created_at=row.created_at,
        model_id=row.model_id,
        template_version=row.template_version,
    )


def version_row(entity: ResumeVersion) -> models.ResumeVersion:
    row = models.ResumeVersion(
        id=entity.id,
        owner_id=entity.owner_id,
        resume_id=entity.resume_id,
        created_at=entity.created_at,
    )
    apply_version(row, entity)
    return row


def apply_version(row: models.ResumeVersion, entity: ResumeVersion) -> None:
    row.number = entity.number
    row.label = entity.label
    row.content = dict(entity.content)
    row.source = str(entity.source)
    row.model_id = entity.model_id
    row.template_version = entity.template_version


def revision(row: models.Revision) -> Revision:
    return Revision(
        id=row.id,
        owner_id=row.owner_id,
        resume_id=row.resume_id,
        request=row.request,
        reply=row.reply,
        proposal=dict(row.proposal) if row.proposal is not None else None,
        model_id=row.model_id,
        template_version=row.template_version,
        created_at=row.created_at,
        applied_version_id=row.applied_version_id,
    )


def revision_row(entity: Revision) -> models.Revision:
    row = models.Revision(
        id=entity.id,
        owner_id=entity.owner_id,
        resume_id=entity.resume_id,
        created_at=entity.created_at,
    )
    apply_revision(row, entity)
    return row


def apply_revision(row: models.Revision, entity: Revision) -> None:
    row.request = entity.request
    row.reply = entity.reply
    row.proposal = entity.proposal
    row.model_id = entity.model_id
    row.template_version = entity.template_version
    row.applied_version_id = entity.applied_version_id


def export(row: models.Export) -> Export:
    return Export(
        id=row.id,
        owner_id=row.owner_id,
        version_id=row.version_id,
        template=Template(row.template),
        status=ExportStatus(row.status),
        created_at=row.created_at,
        storage_key=row.storage_key,
        error_code=row.error_code,
        error_message=row.error_message,
        finished_at=row.finished_at,
    )


def export_row(entity: Export) -> models.Export:
    row = models.Export(
        id=entity.id,
        owner_id=entity.owner_id,
        version_id=entity.version_id,
        created_at=entity.created_at,
    )
    apply_export(row, entity)
    return row


def apply_export(row: models.Export, entity: Export) -> None:
    row.template = str(entity.template)
    row.status = str(entity.status)
    row.storage_key = entity.storage_key
    row.error_code = entity.error_code
    row.error_message = entity.error_message
    row.finished_at = entity.finished_at
