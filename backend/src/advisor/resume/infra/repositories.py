"""SQLAlchemy implementations of the Resume Advisor's repositories.

The six methods come from ``kernel.db.repository.SqlAlchemyRepository``. Every
résumé table is owner-zone, so every repository here is bound to one owner.
"""

from __future__ import annotations

import uuid
from typing import ClassVar

from sqlalchemy import func, select
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.elements import ColumnElement

from advisor.resume.domain import (
    Export,
    ExportFilter,
    ExportRepository,
    ResumeVersion,
    ResumeVersionFilter,
    ResumeVersionRepository,
    Revision,
    RevisionFilter,
    RevisionRepository,
    TailoredResume,
    TailoredResumeFilter,
    TailoredResumeRepository,
)
from advisor.resume.infra import mappers, models
from kernel.db.repository import SqlAlchemyRepository


class SqlAlchemyTailoredResumeRepository(
    SqlAlchemyRepository[TailoredResume, models.Resume, TailoredResumeFilter],
    TailoredResumeRepository,
):
    model = models.Resume
    id_column = models.Resume.id
    created_column = models.Resume.created_at
    owner_column: ClassVar[InstrumentedAttribute[uuid.UUID] | None] = models.Resume.owner_id
    noun = "résumé"

    def to_entity(self, row: models.Resume) -> TailoredResume:
        return mappers.resume(row)

    def to_row(self, entity: TailoredResume) -> models.Resume:
        return mappers.resume_row(entity)

    def apply(self, row: models.Resume, entity: TailoredResume) -> None:
        mappers.apply_resume(row, entity)

    def id_of(self, entity: TailoredResume) -> uuid.UUID:
        return entity.id

    def conditions(self, filter: TailoredResumeFilter) -> list[ColumnElement[bool]]:
        return []


class SqlAlchemyResumeVersionRepository(
    SqlAlchemyRepository[ResumeVersion, models.ResumeVersion, ResumeVersionFilter],
    ResumeVersionRepository,
):
    model = models.ResumeVersion
    id_column = models.ResumeVersion.id
    created_column = models.ResumeVersion.created_at
    owner_column: ClassVar[InstrumentedAttribute[uuid.UUID] | None] = models.ResumeVersion.owner_id
    noun = "version"

    def to_entity(self, row: models.ResumeVersion) -> ResumeVersion:
        return mappers.version(row)

    def to_row(self, entity: ResumeVersion) -> models.ResumeVersion:
        return mappers.version_row(entity)

    def apply(self, row: models.ResumeVersion, entity: ResumeVersion) -> None:
        mappers.apply_version(row, entity)

    def id_of(self, entity: ResumeVersion) -> uuid.UUID:
        return entity.id

    def conditions(self, filter: ResumeVersionFilter) -> list[ColumnElement[bool]]:
        found: list[ColumnElement[bool]] = []
        if filter.resume_id is not None:
            found.append(models.ResumeVersion.resume_id == filter.resume_id)
        if filter.number is not None:
            found.append(models.ResumeVersion.number == filter.number)
        return found

    async def latest_numbers(self) -> dict[uuid.UUID, int]:
        version = models.ResumeVersion
        rows = await self._session.execute(
            select(version.resume_id, func.max(version.number))
            .where(*self._owner_conditions())
            .group_by(version.resume_id)
        )
        return {resume_id: number for resume_id, number in rows.tuples().all()}


class SqlAlchemyRevisionRepository(
    SqlAlchemyRepository[Revision, models.Revision, RevisionFilter],
    RevisionRepository,
):
    model = models.Revision
    id_column = models.Revision.id
    created_column = models.Revision.created_at
    owner_column: ClassVar[InstrumentedAttribute[uuid.UUID] | None] = models.Revision.owner_id
    noun = "revision"

    def to_entity(self, row: models.Revision) -> Revision:
        return mappers.revision(row)

    def to_row(self, entity: Revision) -> models.Revision:
        return mappers.revision_row(entity)

    def apply(self, row: models.Revision, entity: Revision) -> None:
        mappers.apply_revision(row, entity)

    def id_of(self, entity: Revision) -> uuid.UUID:
        return entity.id

    def conditions(self, filter: RevisionFilter) -> list[ColumnElement[bool]]:
        if filter.resume_id is None:
            return []
        return [models.Revision.resume_id == filter.resume_id]


class SqlAlchemyExportRepository(
    SqlAlchemyRepository[Export, models.Export, ExportFilter],
    ExportRepository,
):
    model = models.Export
    id_column = models.Export.id
    created_column = models.Export.created_at
    owner_column: ClassVar[InstrumentedAttribute[uuid.UUID] | None] = models.Export.owner_id
    noun = "export"

    def to_entity(self, row: models.Export) -> Export:
        return mappers.export(row)

    def to_row(self, entity: Export) -> models.Export:
        return mappers.export_row(entity)

    def apply(self, row: models.Export, entity: Export) -> None:
        mappers.apply_export(row, entity)

    def id_of(self, entity: Export) -> uuid.UUID:
        return entity.id

    def conditions(self, filter: ExportFilter) -> list[ColumnElement[bool]]:
        if filter.version_id is None:
            return []
        return [models.Export.version_id == filter.version_id]
