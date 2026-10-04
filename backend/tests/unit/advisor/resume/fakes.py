"""In-memory Resume Advisor storage: the domain's repository interfaces, with no
database."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import date
from types import SimpleNamespace
from typing import Any

from advisor.profile import EvidenceSource, EvidenceView
from advisor.profile.domain import EvidenceGranularity
from advisor.resume.domain import (
    CustomTemplate,
    CustomTemplateFilter,
    CustomTemplateRepository,
    Export,
    ExportFilter,
    ExportRepository,
    OwnerResumes,
    ResumeEvent,
    ResumeUnitOfWork,
    ResumeVersion,
    ResumeVersionFilter,
    ResumeVersionRepository,
    Revision,
    RevisionFilter,
    RevisionRepository,
    TailoredResume,
    TailoredResumeFilter,
    TailoredResumeRepository,
    TemplateReading,
    TemplateReadingFilter,
    TemplateReadingRepository,
)
from advisor.target import DraftBasis, OutdatedReason, TargetRef
from tests.unit.kernel.db.fake_repository import FakeRepository


@dataclass
class Store:
    resumes: dict[uuid.UUID, TailoredResume] = field(default_factory=dict)
    versions: dict[uuid.UUID, ResumeVersion] = field(default_factory=dict)
    revisions: dict[uuid.UUID, Revision] = field(default_factory=dict)
    exports: dict[uuid.UUID, Export] = field(default_factory=dict)
    templates: dict[uuid.UUID, CustomTemplate] = field(default_factory=dict)
    readings: dict[uuid.UUID, TemplateReading] = field(default_factory=dict)
    events: list[ResumeEvent] = field(default_factory=list)


class FakeResumes(FakeRepository[TailoredResume, TailoredResumeFilter], TailoredResumeRepository):
    updated_field = None
    owner_field = "owner_id"
    noun = "résumé"

    def matches(self, entity: TailoredResume, filter: TailoredResumeFilter) -> bool:
        return (
            filter.custom_template_id is None
            or entity.custom_template_id == filter.custom_template_id
        )


class FakeVersions(FakeRepository[ResumeVersion, ResumeVersionFilter], ResumeVersionRepository):
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


class FakeRevisions(FakeRepository[Revision, RevisionFilter], RevisionRepository):
    updated_field = None
    owner_field = "owner_id"
    noun = "revision"

    def matches(self, entity: Revision, filter: RevisionFilter) -> bool:
        return filter.resume_id is None or entity.resume_id == filter.resume_id


class FakeExports(FakeRepository[Export, ExportFilter], ExportRepository):
    updated_field = None
    owner_field = "owner_id"
    noun = "export"

    def matches(self, entity: Export, filter: ExportFilter) -> bool:
        return (
            (filter.version_id is None or entity.version_id == filter.version_id)
            and (filter.trim is None or entity.trim == filter.trim)
            and (filter.status is None or entity.status == filter.status)
        )


class FakeTemplates(FakeRepository[CustomTemplate, CustomTemplateFilter], CustomTemplateRepository):
    updated_field = "updated_at"
    owner_field = "owner_id"
    noun = "template"

    def matches(self, entity: CustomTemplate, filter: CustomTemplateFilter) -> bool:
        return True


class FakeReadings(
    FakeRepository[TemplateReading, TemplateReadingFilter], TemplateReadingRepository
):
    updated_field = None
    owner_field = "owner_id"
    noun = "template reading"

    def matches(self, entity: TemplateReading, filter: TemplateReadingFilter) -> bool:
        return True


class FakeOwner(OwnerResumes):
    def __init__(self, store: Store, owner_id: uuid.UUID) -> None:
        self.resumes = FakeResumes(store.resumes, owner_id=owner_id)
        self.versions = FakeVersions(store.versions, owner_id=owner_id)
        self.revisions = FakeRevisions(store.revisions, owner_id=owner_id)
        self.exports = FakeExports(store.exports, owner_id=owner_id)
        self.templates = FakeTemplates(store.templates, owner_id=owner_id)
        self.readings = FakeReadings(store.readings, owner_id=owner_id)
        self.pending: list[ResumeEvent] = []

    def record(self, event: ResumeEvent) -> None:
        self.pending.append(event)


class FakeResumeUnitOfWork(ResumeUnitOfWork):
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

    def get(self, key: str) -> bytes:
        return self.objects[key]

    def delete(self, key: str) -> None:
        self.objects.pop(key, None)

    def signed_url(self, key: str, *, download_name: str | None = None) -> str:
        saved_as = f"?as={download_name}" if download_name is not None else ""
        return f"https://objects.test/{key}{saved_as}"


class FakeTarget:
    """The Target as it stands now hashes to ``digest``; the comparison is the
    real one."""

    def __init__(self, digest: str = "d1") -> None:
        self.digest = digest

    async def preview(self, owner_id: uuid.UUID, ref: TargetRef) -> Any:
        named = ref.role_id or ref.private_job_posting_id or ""
        return SimpleNamespace(label=f"Target {named[:8]}")

    async def get_outdated_reasons(
        self,
        owner_id: uuid.UUID,
        ref: TargetRef,
        *,
        recorded: DraftBasis | None,
        profile_version: int,
    ) -> tuple[OutdatedReason, ...]:
        if recorded is None:
            return ()
        return recorded.get_outdated_reasons(
            DraftBasis(profile_version=profile_version, target_digest=self.digest)
        )


class FakeProfile:
    def __init__(self, version: int = 0) -> None:
        self.current = version

    async def evidence_ids(self, owner_id: uuid.UUID) -> set[str]:
        return {"e1"}

    async def snapshot(self, owner_id: uuid.UUID) -> Any:
        fact = EvidenceView(
            id="e1",  # type: ignore[arg-type]
            source=EvidenceSource.GITHUB,
            reference="GitHub · ledger-sim",
            fact="40 commits in ledger-sim",
            observed_on=date(2026, 8, 14),
            granularity=EvidenceGranularity.SUMMARY,
            tally=40,
            subject="ledger-sim",
        )
        return SimpleNamespace(
            evidence=(fact,),
            version=self.current,
            positions=(),
            accounts=(SimpleNamespace(source="github", account="mayalin"),),
        )

    async def base_resume_text(self, owner_id: uuid.UUID) -> str | None:
        return None

    async def version(self, owner_id: uuid.UUID) -> int:
        return self.current
