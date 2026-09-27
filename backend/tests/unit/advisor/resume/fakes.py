"""In-memory Resume Advisor storage: the domain's repository interfaces, with no
database."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from advisor.resume.domain import (
    Export,
    ExportFilter,
    ResumeEvent,
    ResumeVersion,
    ResumeVersionFilter,
    Revision,
    RevisionFilter,
    TailoredResume,
    TailoredResumeFilter,
)
from tests.unit.kernel.db.fake_repository import FakeRepository


@dataclass
class Store:
    resumes: dict[uuid.UUID, TailoredResume] = field(default_factory=dict)
    versions: dict[uuid.UUID, ResumeVersion] = field(default_factory=dict)
    revisions: dict[uuid.UUID, Revision] = field(default_factory=dict)
    exports: dict[uuid.UUID, Export] = field(default_factory=dict)
    events: list[ResumeEvent] = field(default_factory=list)


class FakeResumes(FakeRepository[TailoredResume, TailoredResumeFilter]):
    updated_field = None
    owner_field = "owner_id"
    noun = "résumé"

    def matches(self, entity: TailoredResume, filter: TailoredResumeFilter) -> bool:
        return True


class FakeVersions(FakeRepository[ResumeVersion, ResumeVersionFilter]):
    updated_field = None
    owner_field = "owner_id"
    noun = "version"

    def matches(self, entity: ResumeVersion, filter: ResumeVersionFilter) -> bool:
        return (filter.resume_id is None or entity.resume_id == filter.resume_id) and (
            filter.number is None or entity.number == filter.number
        )

    async def latest_numbers(self) -> dict[uuid.UUID, int]:
        latest: dict[uuid.UUID, int] = {}
        for version in self._visible().values():
            latest[version.resume_id] = max(latest.get(version.resume_id, 0), version.number)
        return latest


class FakeRevisions(FakeRepository[Revision, RevisionFilter]):
    updated_field = None
    owner_field = "owner_id"
    noun = "revision"

    def matches(self, entity: Revision, filter: RevisionFilter) -> bool:
        return filter.resume_id is None or entity.resume_id == filter.resume_id


class FakeExports(FakeRepository[Export, ExportFilter]):
    updated_field = None
    owner_field = "owner_id"
    noun = "export"

    def matches(self, entity: Export, filter: ExportFilter) -> bool:
        return filter.version_id is None or entity.version_id == filter.version_id


class FakeOwner:
    def __init__(self, store: Store, owner_id: uuid.UUID) -> None:
        self.resumes = FakeResumes(store.resumes, owner_id=owner_id)
        self.versions = FakeVersions(store.versions, owner_id=owner_id)
        self.revisions = FakeRevisions(store.revisions, owner_id=owner_id)
        self.exports = FakeExports(store.exports, owner_id=owner_id)
        self.pending: list[ResumeEvent] = []

    def record(self, event: ResumeEvent) -> None:
        self.pending.append(event)


class FakeResumeUnitOfWork:
    def __init__(self, store: Store | None = None) -> None:
        self.store = store or Store()

    @asynccontextmanager
    async def for_owner(self, owner_id: uuid.UUID) -> AsyncIterator[FakeOwner]:
        scope = FakeOwner(self.store, owner_id)
        yield scope
        self.store.events.extend(scope.pending)


class FakeObjectStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(self, key: str, content: bytes, content_type: str) -> None:
        self.objects[key] = content

    def signed_url(self, key: str) -> str:
        return f"https://objects.test/{key}"
