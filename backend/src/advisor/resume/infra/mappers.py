"""ORM rows to Resume Advisor entities and back. No rules live here, only shape.

A résumé's Target is a role and an optional opening, as two columns.
"""

from __future__ import annotations

from typing import Any

from advisor.resume.domain import (
    CustomTemplate,
    Export,
    ExportStatus,
    Options,
    ResumeStatus,
    ResumeVersion,
    Revision,
    SectionSlot,
    TailoredResume,
    Template,
    TemplateSpec,
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
        template=Template(row.template) if row.template else None,
        options=options_of(row.options),
        status=ResumeStatus(row.status),
        created_at=row.created_at,
        updated_at=row.updated_at,
        snapshot=dict(row.snapshot) if row.snapshot is not None else None,
        coverage=tuple(row.coverage),
        error_code=row.error_code,
        error_message=row.error_message,
        profile_version=row.profile_version,
        target_digest=row.target_digest,
        section_plan=tuple(SectionSlot.from_dict(slot) for slot in row.section_plan),
        custom_template_id=row.custom_template_id,
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
    row.template = str(entity.template) if entity.template else None
    row.options = options_dict(entity.options)
    row.status = str(entity.status)
    row.snapshot = entity.snapshot
    row.coverage = list(entity.coverage)
    row.error_code = entity.error_code
    row.error_message = entity.error_message
    row.updated_at = entity.updated_at
    row.profile_version = entity.profile_version
    row.target_digest = entity.target_digest
    row.section_plan = [slot.to_dict() for slot in entity.section_plan]
    row.custom_template_id = entity.custom_template_id


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
        template=Template(row.template) if row.template else None,
        status=ExportStatus(row.status),
        created_at=row.created_at,
        trim=row.trim,
        spec=dict(row.spec) if row.spec is not None else None,
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
    row.template = str(entity.template) if entity.template else None
    row.trim = entity.trim
    row.spec = entity.spec
    row.status = str(entity.status)
    row.storage_key = entity.storage_key
    row.error_code = entity.error_code
    row.error_message = entity.error_message
    row.finished_at = entity.finished_at


def custom_template(row: models.CustomTemplate) -> CustomTemplate:
    return CustomTemplate(
        id=row.id,
        owner_id=row.owner_id,
        name=row.name,
        spec=TemplateSpec.from_dict(row.spec),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def custom_template_row(entity: CustomTemplate) -> models.CustomTemplate:
    row = models.CustomTemplate(
        id=entity.id, owner_id=entity.owner_id, created_at=entity.created_at
    )
    apply_custom_template(row, entity)
    return row


def apply_custom_template(row: models.CustomTemplate, entity: CustomTemplate) -> None:
    row.name = entity.name
    row.spec = entity.spec.to_dict()
    row.updated_at = entity.updated_at
