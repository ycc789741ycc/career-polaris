"""Resume Advisor use cases against in-memory storage: requesting, versions,
applying a chat edit, exporting and recording failures, with no database and
no model."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from advisor.profile import CitationHandles, EvidenceSource, EvidenceView
from advisor.profile.domain import EvidenceGranularity
from advisor.resume import Options, ResumeService, Template
from advisor.resume import service as resume_service
from advisor.resume.domain import (
    Bullet,
    Position,
    ResumeContent,
    ResumeStatus,
    ResumeVersionSaved,
    Revision,
    VersionSource,
)
from advisor.target import DraftBasis, OutdatedReason, TargetRef
from kernel.errors import ConflictError, NotFoundError, ValidationError
from tests.unit.advisor.resume.fakes import FakeObjectStore, FakeResumeUnitOfWork

OWNER = uuid.UUID("00000000-0000-0000-0000-000000000001")
OTHER = uuid.UUID("00000000-0000-0000-0000-000000000002")


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
        return SimpleNamespace(evidence=())

    async def version(self, owner_id: uuid.UUID) -> int:
        return self.current


def _service(
    uow: FakeResumeUnitOfWork,
    store: FakeObjectStore | None = None,
    *,
    profile: FakeProfile | None = None,
    digest: str = "d1",
) -> ResumeService:
    return ResumeService(
        uow,
        target=FakeTarget(digest),  # type: ignore[arg-type]
        profile=profile or FakeProfile(),  # type: ignore[arg-type]
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
    assert done.download_url is not None and ".pdf" in done.download_url
    [pdf] = store.objects.values()
    assert pdf.startswith(b"%PDF")
    with pytest.raises(NotFoundError):
        await service.request_export(OWNER, resume_id, number=2)


async def test_an_unchanged_export_is_reused_and_a_changed_one_rendered_again() -> None:
    uow = FakeResumeUnitOfWork()
    service = _service(uow)
    resume_id = await _resume(service)
    await service.save_version(OWNER, resume_id, content=_content())
    first = await service.request_export(OWNER, resume_id, number=1)
    await service.export(OWNER, first.id)

    again = await service.request_export(OWNER, resume_id, number=1)
    assert (again.id, again.status) == (first.id, "ready")

    await service.update_settings(
        OWNER, resume_id, template=Template.ORGANIC, options=Options(trim=True)
    )
    trimmed = await service.request_export(OWNER, resume_id, number=1)
    await service.update_settings(
        OWNER, resume_id, template=Template.PLAIN, options=Options(trim=True)
    )
    plain = await service.request_export(OWNER, resume_id, number=1)

    assert len({first.id, trimmed.id, plain.id}) == 3
    assert trimmed.status == plain.status == "rendering"


async def test_an_export_renders_the_trim_asked_for_when_it_was_clicked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uow = FakeResumeUnitOfWork()
    service = _service(uow)
    resume_id = await _resume(service)
    await service.save_version(OWNER, resume_id, content=_content())
    await service.update_settings(
        OWNER, resume_id, template=Template.ORGANIC, options=Options(trim=True)
    )
    requested = await service.request_export(OWNER, resume_id, number=1)
    # Changed between the click and the render: the click's settings win.
    await service.update_settings(
        OWNER, resume_id, template=Template.PLAIN, options=Options(trim=False)
    )
    rendered: list[tuple[Template, Options]] = []

    def render_html(content: Any, *, template: Template, options: Options) -> str:
        rendered.append((template, options))
        return "<p>page</p>"

    monkeypatch.setattr(resume_service, "render_html", render_html)
    await service.export(OWNER, requested.id)

    [(template, options)] = rendered
    assert template is Template.ORGANIC and options.trim is True


async def test_a_ready_export_downloads_under_the_persons_name_and_the_role() -> None:
    uow = FakeResumeUnitOfWork()
    service = _service(uow)
    resume_id = await _resume(service)
    await service.save_version(OWNER, resume_id, content=_content())
    requested = await service.request_export(OWNER, resume_id, number=1)
    await service.export(OWNER, requested.id)

    done = await service.get_export(OWNER, requested.id)

    label = uow.store.resumes[resume_id].target_label
    assert done.download_url is not None
    assert done.download_url.endswith(f"?as=Maya Lin Chen — {label}.pdf")


def test_every_template_is_listed_as_the_renderer_draws_it() -> None:
    listed = _service(FakeResumeUnitOfWork()).templates()

    assert [t.look.template for t in listed.items] == [Template.ORGANIC, Template.PLAIN]
    organic = listed.items[0]
    assert (organic.look.rule, organic.look.heading_font) == ("3px solid #c67139", "Caprasimo")
    assert (organic.trimmed_bullets, organic.trimmed_skills) == (3, 12)
    assert (organic.page_width_mm, organic.page_height_mm) == (210, 297)


async def test_a_failure_is_recorded_on_the_resume_and_generation_skips_it() -> None:
    uow = FakeResumeUnitOfWork()
    service = _service(uow)
    resume_id = await _resume(service)

    await service._fail(OWNER, resume_id, code="target_unusable", message="Nothing to write")
    # A résumé no longer drafting is left alone: a retry would spend the key again.
    await service.generate(OWNER, resume_id)

    [summary] = (await service.saved(OWNER)).items
    assert summary.status == "failed" and summary.error_code == "target_unusable"


# --- outdated, regenerated only when asked (ADR 0035) -------------------------


def _written(uow: FakeResumeUnitOfWork, resume_id: uuid.UUID, *, version: int, digest: str) -> None:
    resume = uow.store.resumes[resume_id]
    resume.written(
        snapshot={},
        label=resume.target_label,
        coverage=(),
        profile_version=version,
        target_digest=digest,
        at=resume.created_at,
    )


async def test_redrafting_asks_for_the_next_version_and_refuses_while_writing() -> None:
    uow = FakeResumeUnitOfWork()
    service = _service(uow)
    resume_id = await _resume(service)

    with pytest.raises(ConflictError):
        await service.redraft(OWNER, resume_id)

    _written(uow, resume_id, version=1, digest="d1")
    redrafting = await service.redraft(OWNER, resume_id)

    assert redrafting.status == "drafting"
    assert uow.store.resumes[resume_id].status is ResumeStatus.DRAFTING
    with pytest.raises(NotFoundError):
        await service.redraft(OTHER, resume_id)


@pytest.mark.parametrize(
    ("version", "digest", "reasons"),
    [
        (1, "d1", ()),
        (2, "d1", (OutdatedReason.EVIDENCE,)),
        (1, "d2", (OutdatedReason.TARGET,)),
    ],
)
async def test_a_written_resume_is_outdated_by_what_moved_on(
    version: int, digest: str, reasons: tuple[OutdatedReason, ...]
) -> None:
    uow = FakeResumeUnitOfWork()
    service = _service(uow, profile=FakeProfile(version=version), digest=digest)
    resume_id = await _resume(service)
    _written(uow, resume_id, version=1, digest="d1")

    view = await service.get(OWNER, resume_id)

    assert view.outdated_by == reasons and view.is_outdated == bool(reasons)


async def test_a_manual_edit_keeps_what_the_resume_was_written_from() -> None:
    uow = FakeResumeUnitOfWork()
    service = _service(uow, profile=FakeProfile(version=1), digest="d1")
    resume_id = await _resume(service)
    _written(uow, resume_id, version=1, digest="d1")

    await service.save_version(OWNER, resume_id, content=_content("Rewrote it myself"))

    stored = uow.store.resumes[resume_id]
    assert (stored.profile_version, stored.target_digest) == (1, "d1")
    assert (await service.get(OWNER, resume_id)).outdated_by == ()


# --- what the writing prompts read (ADR 0037) ---------------------------------


def test_the_writing_prompts_read_each_fact_with_its_date() -> None:
    fact = EvidenceView(
        id=uuid.uuid4(),
        source=EvidenceSource.JIRA,
        reference="Jira · PAY",
        fact="40 issues done in PAY",
        observed_on=date(2026, 8, 14),
        granularity=EvidenceGranularity.SUMMARY,
        tally=40,
        subject="PAY",
    )
    profile = SimpleNamespace(positions=(), evidence=(fact,))

    inputs = resume_service._write_inputs(
        profile,  # type: ignore[arg-type]
        CitationHandles([fact.id]),
        label="Staff Engineer · Northwind",
        requirements="- Own reliability",
        coverage_rows=(),
        options=Options(),
        base_resume="(none uploaded)",
    )

    assert inputs["evidence"] == "[E1] (jira, latest 2026-08-14) Jira · PAY: 40 issues done in PAY"
    assert resume_service._WRITE == ("resume_write", "v2")
    assert resume_service._REVISE == ("resume_revise", "v2")
