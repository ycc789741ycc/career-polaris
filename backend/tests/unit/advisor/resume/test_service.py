"""Resume Advisor use cases against in-memory storage: requesting, versions,
applying a chat edit, exporting and recording failures, with no database and
no model."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from advisor.resume import Options, ResumeService, Template
from advisor.resume.domain import (
    Bullet,
    Position,
    ResumeContent,
    ResumeStatus,
    ResumeVersionSaved,
    Revision,
    VersionSource,
)
from advisor.target import TargetRef
from kernel.errors import NotFoundError, ValidationError
from tests.unit.advisor.resume.fakes import FakeObjectStore, FakeResumeUnitOfWork

OWNER = uuid.UUID("00000000-0000-0000-0000-000000000001")
OTHER = uuid.UUID("00000000-0000-0000-0000-000000000002")


class FakeTarget:
    async def preview(self, owner_id: uuid.UUID, ref: TargetRef) -> Any:
        return SimpleNamespace(label=f"Target {ref.role_id[:8]}")


class FakeProfile:
    async def evidence_ids(self, owner_id: uuid.UUID) -> set[str]:
        return {"e1"}

    async def snapshot(self, owner_id: uuid.UUID) -> Any:
        return SimpleNamespace(evidence=())


def _service(uow: FakeResumeUnitOfWork, store: FakeObjectStore | None = None) -> ResumeService:
    return ResumeService(
        uow,
        target=FakeTarget(),  # type: ignore[arg-type]
        profile=FakeProfile(),  # type: ignore[arg-type]
        assessment=None,  # type: ignore[arg-type]
        gateway=None,  # type: ignore[arg-type]
        object_store=store or FakeObjectStore(),  # type: ignore[arg-type]
    )


def _content(line: str = "Owned the retry layer for payments-svc") -> dict[str, Any]:
    return ResumeContent(
        name="Maya Lin Chen",
        headline="Backend Engineer",
        contact="maya@example.com",
        summary="Builds payment systems.",
        experience=(
            Position("Backend Engineer", "Kestrel", "2022 — now", (Bullet(line, ("e1",)),)),
        ),
        skills=("Go", "Postgres"),
    ).to_dict()


async def _resume(service: ResumeService) -> uuid.UUID:
    summary = await service.request(
        OWNER,
        TargetRef(str(uuid.uuid4()), str(uuid.uuid4())),
        template=Template.ORGANIC,
        options=Options(),
    )
    return summary.id


async def test_saved_resumes_list_by_last_change_with_their_latest_version() -> None:
    uow = FakeResumeUnitOfWork()
    service = _service(uow)
    older = await _resume(service)
    newer = await _resume(service)

    await service.save_version(OWNER, older, content=_content())
    await service.save_version(OWNER, older, content=_content("Cut p99 latency by 70%"))

    saved = (await service.saved(OWNER)).items
    assert [s.id for s in saved] == [older, newer]
    assert [s.latest_version for s in saved] == [2, None]
    assert uow.store.events == [
        ResumeVersionSaved(owner_id=OWNER, resume_id=older, number=1, source=VersionSource.MANUAL),
        ResumeVersionSaved(owner_id=OWNER, resume_id=older, number=2, source=VersionSource.MANUAL),
    ]
    assert (await service.saved(OTHER)).items == ()


async def test_a_resume_shows_its_versions_newest_first_and_any_one_on_request() -> None:
    uow = FakeResumeUnitOfWork()
    service = _service(uow)
    resume_id = await _resume(service)
    await service.save_version(OWNER, resume_id, content=_content())
    await service.save_version(OWNER, resume_id, content=_content("Cut p99 latency by 70%"))

    latest = await service.get(OWNER, resume_id)
    first = await service.get(OWNER, resume_id, number=1)

    assert [v.number for v in latest.versions] == [2, 1]
    assert latest.version is not None and latest.version.number == 2
    assert first.content is not None
    assert first.content.experience[0].bullets[0].text == "Owned the retry layer for payments-svc"
    with pytest.raises(NotFoundError):
        await service.get(OWNER, resume_id, number=9)
    with pytest.raises(NotFoundError):
        await service.get(OTHER, resume_id)


async def test_an_accepted_chat_edit_becomes_a_version_once() -> None:
    uow = FakeResumeUnitOfWork()
    service = _service(uow)
    resume_id = await _resume(service)
    async with uow.for_owner(OWNER) as mine:
        revision = await mine.revisions.create(
            Revision(
                id=uuid.uuid4(),
                owner_id=OWNER,
                resume_id=resume_id,
                request="Tighten it",
                reply="Here you go",
                proposal=_content("Tightened line"),
                model_id="m",
                template_version="v1",
                created_at=datetime.now(UTC),
            )
        )

    version = await service.apply_revision(OWNER, resume_id, revision.id)

    assert version.number == 1 and version.source is VersionSource.CHAT
    assert uow.store.revisions[revision.id].applied_version_id == version.id
    with pytest.raises(ValidationError):
        await service.apply_revision(OWNER, resume_id, revision.id)


async def test_an_export_renders_is_stored_and_links_once_ready() -> None:
    uow = FakeResumeUnitOfWork()
    store = FakeObjectStore()
    service = _service(uow, store)
    resume_id = await _resume(service)
    await service.save_version(OWNER, resume_id, content=_content())

    requested = await service.request_export(OWNER, resume_id, number=1)
    assert requested.status == "rendering" and requested.download_url is None

    await service.export(OWNER, requested.id)

    done = await service.get_export(OWNER, requested.id)
    assert done.status == "ready"
    assert done.download_url is not None and done.download_url.endswith(".pdf")
    [pdf] = store.objects.values()
    assert pdf.startswith(b"%PDF")
    with pytest.raises(NotFoundError):
        await service.request_export(OWNER, resume_id, number=2)


async def test_a_failure_is_recorded_on_the_resume_and_generation_skips_it() -> None:
    uow = FakeResumeUnitOfWork()
    service = _service(uow)
    resume_id = await _resume(service)

    await service._fail(OWNER, resume_id, code="target_unusable", message="Nothing to write")
    # A résumé no longer drafting is left alone: a retry would spend the key again.
    await service.generate(OWNER, resume_id)

    [summary] = (await service.saved(OWNER)).items
    assert summary.status == "failed" and summary.error_code == "target_unusable"


# --- after Fill the gap (ADR 0023) -------------------------------------------


async def test_regenerating_a_target_with_no_resume_does_nothing() -> None:
    service = _service(FakeResumeUnitOfWork())

    assert await service.regenerate(OWNER, TargetRef(str(uuid.uuid4()))) is None


async def test_regenerating_writes_the_targets_resume_again_as_an_answers_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uow = FakeResumeUnitOfWork()
    service = _service(uow)
    resume_id = await _resume(service)
    ref = next(iter(uow.store.resumes.values()))
    target = TargetRef(str(ref.role_id), str(ref.job_posting_id))
    uow.store.resumes[resume_id].status = ResumeStatus.READY
    written: list[tuple[uuid.UUID, VersionSource]] = []

    async def generate(owner_id: uuid.UUID, resume_id: uuid.UUID, *, source: VersionSource) -> None:
        written.append((resume_id, source))

    monkeypatch.setattr(service, "generate", generate)

    assert await service.regenerate(OWNER, target) == resume_id
    assert written == [(resume_id, VersionSource.ANSWERS)]
    assert uow.store.resumes[resume_id].status is ResumeStatus.DRAFTING
