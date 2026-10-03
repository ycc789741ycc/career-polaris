"""How the Resume Advisor's use cases reach stored data: interfaces in domain
terms.

Every repository has the same six methods (ADR 0011): ``create``, ``get``,
``get_list`` (newest first, paged), ``get_count``, ``update`` and ``delete``,
over one frozen filter per aggregate whose unset fields do not filter. The one
extra method, ``ResumeVersionRepository.latest_numbers``, is an aggregate
(the highest version number per résumé) the six cannot express without loading
every version's content.

All résumé data is owner-zone, so the unit of work has one scope: one user's
data, in one transaction. Events recorded in it are committed with it.
"""

from __future__ import annotations

import uuid
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Protocol

from advisor.resume.domain.content import Template
from advisor.resume.domain.events import ResumeEvent
from advisor.resume.domain.export import Export, ExportStatus
from advisor.resume.domain.revision import Revision
from advisor.resume.domain.tailored_resume import ResumeVersion, TailoredResume


class Repository[Entity, Filter](Protocol):
    """The six methods, as every résumé repository has them."""

    async def create(self, entity: Entity) -> Entity: ...

    async def get(self, entity_id: uuid.UUID) -> Entity | None: ...

    async def get_list(
        self, filter: Filter, page: int = 1, page_size: int | None = None
    ) -> list[Entity]: ...

    async def get_count(self, filter: Filter) -> int: ...

    async def update(self, entity: Entity) -> Entity: ...

    async def delete(self, entity_id: uuid.UUID) -> None: ...


@dataclass(frozen=True, slots=True)
class TailoredResumeFilter:
    """Nothing to filter on yet: a user's résumés are listed whole."""


class TailoredResumeRepository(Repository[TailoredResume, TailoredResumeFilter], Protocol): ...


@dataclass(frozen=True, slots=True)
class ResumeVersionFilter:
    resume_id: uuid.UUID | None = None
    number: int | None = None


class ResumeVersionRepository(Repository[ResumeVersion, ResumeVersionFilter], Protocol):
    async def latest_numbers(self) -> dict[uuid.UUID, int]:
        """The highest version number of each résumé that has one."""
        ...


@dataclass(frozen=True, slots=True)
class RevisionFilter:
    resume_id: uuid.UUID | None = None


class RevisionRepository(Repository[Revision, RevisionFilter], Protocol): ...


@dataclass(frozen=True, slots=True)
class ExportFilter:
    version_id: uuid.UUID | None = None
    template: Template | None = None
    trim: bool | None = None
    status: ExportStatus | None = None


class ExportRepository(Repository[Export, ExportFilter], Protocol): ...


class OwnerResumes(Protocol):
    resumes: TailoredResumeRepository
    versions: ResumeVersionRepository
    revisions: RevisionRepository
    exports: ExportRepository

    def record(self, event: ResumeEvent) -> None: ...


class ResumeUnitOfWork(Protocol):
    def for_owner(self, owner_id: uuid.UUID) -> AbstractAsyncContextManager[OwnerResumes]: ...
