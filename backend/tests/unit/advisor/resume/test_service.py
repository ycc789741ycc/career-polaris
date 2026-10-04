"""Resume Advisor use cases against in-memory storage: requesting, versions,
applying a chat edit, exporting and recording failures, with no database and
no model."""

from __future__ import annotations

import uuid
from dataclasses import replace
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
    ResumeStatus,
    ResumeVersionSaved,
    Revision,
    SectionKind,
    SectionSlot,
    TemplateSpec,
    VersionSource,
    get_built_in_spec,
)
from advisor.target import OutdatedReason, TargetRef, TargetSnapshot
from advisor.target.domain import Requirement, RequirementBasis
from kernel.errors import ConflictError, NotFoundError, ValidationError
from tests.unit.advisor.resume.builders import get_lines, make_content
from tests.unit.advisor.resume.fakes import (
    FakeGapFill,
    FakeObjectStore,
    FakeProfile,
    FakeResumeUnitOfWork,
    FakeTarget,
)

OWNER = uuid.UUID("00000000-0000-0000-0000-000000000001")
OTHER = uuid.UUID("00000000-0000-0000-0000-000000000002")


def _service(
    uow: FakeResumeUnitOfWork,
    store: FakeObjectStore | None = None,
    *,
    profile: FakeProfile | None = None,
    digest: str = "d1",
    gateway: Any = None,
) -> ResumeService:
    return ResumeService(
        uow,
        target=FakeTarget(digest),  # type: ignore[arg-type]
        profile=profile or FakeProfile(),  # type: ignore[arg-type]
        assessment=None,  # type: ignore[arg-type]
        gapfill=FakeGapFill(),  # type: ignore[arg-type]
        gateway=gateway,
        object_store=store or FakeObjectStore(),  # type: ignore[arg-type]
    )


def _content(line: str = "Owned the retry layer for payments-svc") -> dict[str, Any]:
    return make_content(Bullet(line, ("e1",))).to_dict()


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
    assert get_lines(first.content)[0].text == "Owned the retry layer for payments-svc"
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
    rendered: list[tuple[TemplateSpec, Options]] = []

    def render_html(content: Any, *, spec: TemplateSpec, options: Options) -> str:
        rendered.append((spec, options))
        return "<p>page</p>"

    monkeypatch.setattr(resume_service, "render_html", render_html)
    await service.export(OWNER, requested.id)

    [(spec, options)] = rendered
    assert spec == get_built_in_spec(Template.ORGANIC) and options.trim is True


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


async def test_every_built_in_template_is_listed_as_the_renderer_draws_it() -> None:
    listed = await _service(FakeResumeUnitOfWork()).templates(OWNER)

    assert [t.id for t in listed.items] == ["organic", "plain"]
    organic = listed.items[0]
    assert organic.is_built_in
    assert (organic.spec.get_rule_css(), organic.spec.heading_font) == (
        "3px solid #c67139",
        "Caprasimo",
    )
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
    profile = SimpleNamespace(
        positions=(),
        evidence=(fact,),
        accounts=(SimpleNamespace(source="github", account="mayalin"),),
    )

    inputs = resume_service._write_inputs(
        profile,  # type: ignore[arg-type]
        CitationHandles([fact.id]),
        label="Staff Engineer · Northwind",
        requirements="- Own reliability",
        coverage_rows=(),
        options=Options(),
        base_resume="(none uploaded)",
        plan=(SectionSlot(SectionKind.EXPERIENCE), SectionSlot(SectionKind.CUSTOM, "Awards")),
    )

    assert inputs["sections"] == "- experience\n- custom: Awards"
    assert inputs["evidence"] == "[E1] (jira, latest 2026-08-14) Jira · PAY: 40 issues done in PAY"
    assert inputs["accounts"] == "- github: mayalin"
    assert resume_service._WRITE == ("resume_write", "v5")
    assert resume_service._REVISE == ("resume_revise", "v5")


# --- sections you choose (ADR 0039) -------------------------------------------

SNAPSHOT = TargetSnapshot(
    ref=TargetRef(str(uuid.uuid4())),
    title="Staff Engineer",
    company="Northwind",
    role_id=None,
    role_name="Staff Engineer",
    requirements=(Requirement("Own reliability", 1.0, "senior"),),
    basis=RequirementBasis.ROLE,
    fit_score=70,
    dimensions=(),
    uncovered=(),
    requirement_map={},
    taken_at=datetime(2026, 10, 1, tzinfo=UTC),
).to_dict()


class SectionGateway:
    """Writes the asked-for section from ``reply``, and records what it saw."""

    def __init__(self, reply: dict[str, Any]) -> None:
        self.reply = reply
        self.inputs: list[dict[str, str]] = []

    async def run(self, owner_id: uuid.UUID, *, inputs: dict[str, str], **kwargs: Any) -> Any:
        self.inputs.append(inputs)
        return SimpleNamespace(
            value=kwargs["output_schema"].model_validate({"section": self.reply}),
            model_id="claude-opus-5",
            template_version="resume_section@v1",
        )

    async def estimate(self, owner_id: uuid.UUID, **kwargs: Any) -> Any:
        return SimpleNamespace(
            cost_usd="0.02", model_id="claude-opus-5", input_tokens=900, rate_is_published=True
        )


async def _ready(uow: FakeResumeUnitOfWork, service: ResumeService) -> uuid.UUID:
    resume_id = await _resume(service)
    await service.save_version(OWNER, resume_id, content=_content())
    _written(uow, resume_id, version=0, digest="d1")
    uow.store.resumes[resume_id].snapshot = SNAPSHOT
    return resume_id


EDUCATION = SectionSlot(SectionKind.EDUCATION)


async def test_moving_and_removing_sections_saves_a_version_and_the_plan() -> None:
    uow = FakeResumeUnitOfWork()
    service = _service(uow)  # no gateway: nothing here may call a model
    resume_id = await _ready(uow, service)
    current = make_content(Bullet("Owned the retry layer for payments-svc", ("e1",)))
    summary, experience, _skills = current.sections

    await service.save_version(
        OWNER,
        resume_id,
        content=replace(current, sections=(experience, summary)).to_dict(),
    )

    plan = uow.store.resumes[resume_id].section_plan
    assert plan[:2] == (SectionSlot(SectionKind.EXPERIENCE), SectionSlot(SectionKind.SUMMARY))
    # Every other kind is still held, hidden (ADR 0043).
    assert len(plan) == 8 and not any(s.is_shown for s in plan[2:])
    with pytest.raises(ValidationError, match="experience"):
        await service.save_version(
            OWNER, resume_id, content=replace(current, sections=(summary,)).to_dict()
        )


class WriteGateway:
    """Writes the whole résumé from ``sections``, and records what it saw."""

    def __init__(self, sections: list[dict[str, Any]]) -> None:
        self.sections = sections
        self.inputs: list[dict[str, str]] = []

    async def run(self, owner_id: uuid.UUID, *, inputs: dict[str, str], **kwargs: Any) -> Any:
        self.inputs.append(inputs)
        reply = {"name": "Maya Lin Chen", "sections": self.sections}
        return SimpleNamespace(
            value=kwargs["output_schema"].model_validate(reply),
            model_id="claude-opus-5",
            template_version="resume_write@v4",
        )


class SnapshotTarget(FakeTarget):
    async def snapshot(self, owner_id: uuid.UUID, ref: TargetRef) -> TargetSnapshot:
        return TargetSnapshot.from_dict(SNAPSHOT)


class NoAssessment:
    async def latest(self, owner_id: uuid.UUID) -> None:
        return None


async def test_a_write_fills_every_section_and_keeps_each_ones_place_and_state() -> None:
    cited = {"text": "Built the ledger simulator", "evidence_ids": ["E1"]}
    gateway = WriteGateway(
        [
            {"kind": "summary", "text": "Builds payment systems."},
            {
                "kind": "experience",
                "entries": [
                    {"title": "Payments platform, backend", "org": "kestrel", "bullets": [cited]}
                ],
            },
            {"kind": "skills", "items": ["Go"]},
            {"kind": "side_projects", "entries": [{"title": "ledger-sim", "bullets": [cited]}]},
        ]
    )
    uow = FakeResumeUnitOfWork()
    service = ResumeService(
        uow,
        target=SnapshotTarget(),  # type: ignore[arg-type]
        profile=FakeProfile(),  # type: ignore[arg-type]
        assessment=NoAssessment(),  # type: ignore[arg-type]
        gapfill=FakeGapFill(),  # type: ignore[arg-type]
        gateway=gateway,  # type: ignore[arg-type]
        object_store=FakeObjectStore(),  # type: ignore[arg-type]
    )
    resume_id = await _ready(uow, service)
    # Skills moved first and hidden; the rest as an older résumé had them.
    summary, experience, skills = make_content(Bullet("x", ("e1",))).sections
    await service.save_version(
        OWNER,
        resume_id,
        content=replace(
            make_content(Bullet("x", ("e1",))),
            sections=(replace(skills, is_shown=False), summary, experience),
        ).to_dict(),
    )
    await service.redraft(OWNER, resume_id)

    await service.generate(OWNER, resume_id)

    view = await service.get(OWNER, resume_id)
    assert view.summary.status == "ready" and view.content is not None
    asked = gateway.inputs[0]["sections"].splitlines()
    assert asked[:3] == ["- skills", "- summary", "- experience"] and len(asked) == 8
    assert gateway.inputs[0]["accounts"] == "- github: mayalin"
    assert [(s.kind, s.is_shown) for s in view.content.sections[:4]] == [
        (SectionKind.SKILLS, False),
        (SectionKind.SUMMARY, True),
        (SectionKind.EXPERIENCE, True),
        (SectionKind.SIDE_PROJECTS, False),
    ]
    side = view.content.get_section(SectionSlot(SectionKind.SIDE_PROJECTS))
    assert side is not None and side.entries[0].bullets[0].evidence_ids == ("e1",)
    assert view.section_plan == view.content.get_plan()


def _writer(uow: FakeResumeUnitOfWork, gateway: Any, gapfill: FakeGapFill) -> ResumeService:
    return ResumeService(
        uow,
        target=SnapshotTarget(),  # type: ignore[arg-type]
        profile=FakeProfile(),  # type: ignore[arg-type]
        assessment=NoAssessment(),  # type: ignore[arg-type]
        gapfill=gapfill,  # type: ignore[arg-type]
        gateway=gateway,
        object_store=FakeObjectStore(),  # type: ignore[arg-type]
    )


# The snapshot's one requirement maps to nothing: a gap, keyed by its words.
RELIABILITY_GAP = "req:own-reliability"


def _claiming_reliability() -> WriteGateway:
    return WriteGateway(
        [
            {
                "kind": "experience",
                "entries": [
                    {
                        "title": "Payments platform, backend",
                        "bullets": [
                            {
                                "text": "Ran the incident reviews for payments",
                                "evidence_ids": ["E1"],
                                "answers": "Own reliability",
                            }
                        ],
                    }
                ],
            }
        ]
    )


async def test_a_gap_is_written_from_what_the_user_answered_about_it() -> None:
    uow = FakeResumeUnitOfWork()
    gateway = _claiming_reliability()
    service = _writer(uow, gateway, FakeGapFill((RELIABILITY_GAP, "e1")))
    resume_id = await _resume(service)

    await service.generate(OWNER, resume_id)

    view = await service.get(OWNER, resume_id)
    assert view.summary.status == "ready", view.summary.error_message
    assert gateway.inputs[0]["coverage"] == "- gap: Own reliability (answered in [E1])"
    [row] = view.coverage
    assert (row.verdict, [a.id for a in row.answers]) == ("gap", ["e1"])


async def test_a_claim_on_a_gap_nobody_answered_about_is_dropped_not_the_resume() -> None:
    """The model labelling a cited line with a gap it cannot back costs the
    label, not the write the user paid for (ADR 0046)."""
    uow = FakeResumeUnitOfWork()
    service = _writer(uow, _claiming_reliability(), FakeGapFill())
    resume_id = await _resume(service)

    await service.generate(OWNER, resume_id)

    view = await service.get(OWNER, resume_id)
    assert view.summary.status == "ready", view.summary.error_message
    assert view.content is not None
    [line] = list(view.content.bullets())
    assert (line.text, line.evidence_ids, line.answers) == (
        "Ran the incident reviews for payments",
        ("e1",),
        None,
    )


async def test_showing_a_section_is_an_edit_that_spends_nothing() -> None:
    uow = FakeResumeUnitOfWork()
    service = _service(uow)  # no gateway: nothing here may call a model
    resume_id = await _ready(uow, service)
    current = (await service.get(OWNER, resume_id)).content
    assert current is not None

    shown = replace(
        current,
        sections=tuple(
            replace(s, is_shown=True) if s.kind is SectionKind.EDUCATION else s
            for s in current.sections
        ),
    )
    await service.save_version(OWNER, resume_id, content=shown.to_dict())

    plan = uow.store.resumes[resume_id].section_plan
    assert next(s for s in plan if s == EDUCATION).is_shown
    assert uow.store.resumes[resume_id].status is ResumeStatus.READY


async def test_adding_a_section_fills_only_it_and_keeps_every_other_line() -> None:
    uow = FakeResumeUnitOfWork()
    gateway = SectionGateway(
        {
            "kind": "education",
            "entries": [
                {
                    "title": "BSc Computer Science",
                    "org": "TU Berlin",
                    "when": "2016",
                    "bullets": [{"text": "Thesis on ledgers", "evidence_ids": ["E1"]}],
                }
            ],
        }
    )
    service = _service(uow, gateway=gateway)
    resume_id = await _ready(uow, service)
    before = (await service.get(OWNER, resume_id)).content

    priced = await service.estimate_section(OWNER, resume_id, EDUCATION)
    asked = await service.request_section(OWNER, resume_id, EDUCATION)
    assert priced["cost_usd"] == "0.02" and asked.status == "filling"
    # Shown in its place among the sections the résumé holds.
    plan = uow.store.resumes[resume_id].section_plan
    assert next(s for s in plan if s == EDUCATION).is_shown

    await service.fill_section(OWNER, resume_id, EDUCATION)

    after = await service.get(OWNER, resume_id)
    assert after.summary.status == "ready" and after.content is not None and before is not None
    assert after.content.sections[:3] == before.sections[:3]
    education = after.content.get_section(EDUCATION)
    assert education is not None and education.is_shown
    assert education.entries[0].bullets[0].evidence_ids == ("e1",)
    assert gateway.inputs[0]["section"] == "education"


async def test_a_section_nothing_supports_is_saved_empty() -> None:
    uow = FakeResumeUnitOfWork()
    service = _service(uow, gateway=SectionGateway({"kind": "education"}))
    resume_id = await _ready(uow, service)
    await service.request_section(OWNER, resume_id, EDUCATION)

    await service.fill_section(OWNER, resume_id, EDUCATION)

    view = await service.get(OWNER, resume_id)
    assert view.content is not None
    education = view.content.get_section(EDUCATION)
    assert education is not None and education.is_empty
    assert view.versions[0].number == 2


async def test_a_reply_for_another_section_leaves_the_resume_ready_with_the_reason() -> None:
    uow = FakeResumeUnitOfWork()
    service = _service(uow, gateway=SectionGateway({"kind": "certifications", "items": ["CKA"]}))
    resume_id = await _ready(uow, service)
    await service.request_section(OWNER, resume_id, EDUCATION)

    await service.fill_section(OWNER, resume_id, EDUCATION)

    stored = uow.store.resumes[resume_id]
    assert (stored.status, stored.error_code) == (ResumeStatus.READY, "ai_output_invalid")
    assert len((await service.get(OWNER, resume_id)).versions) == 1


async def test_a_section_already_there_or_while_busy_is_refused() -> None:
    uow = FakeResumeUnitOfWork()
    service = _service(uow, gateway=SectionGateway({"kind": "education"}))
    resume_id = await _ready(uow, service)

    with pytest.raises(ValidationError, match="already has lines"):
        await service.request_section(OWNER, resume_id, SectionSlot(SectionKind.SKILLS))
    with pytest.raises(ValidationError, match="heading"):
        await service.request_section(OWNER, resume_id, SectionSlot(SectionKind.CUSTOM))
    await service.request_section(OWNER, resume_id, EDUCATION)
    with pytest.raises(ConflictError):
        await service.request_section(OWNER, resume_id, SectionSlot(SectionKind.CERTIFICATIONS))
    with pytest.raises(NotFoundError):
        await service.request_section(OTHER, resume_id, SectionSlot(SectionKind.CERTIFICATIONS))


# -- a job in the background (ADR 0042) -------------------------------------------


async def test_a_first_draft_cancelled_is_no_longer_listed() -> None:
    uow = FakeResumeUnitOfWork()
    service = _service(uow)
    resume_id = await _resume(service)
    [job] = await service.running_jobs(OWNER)
    assert (job.kind, job.id) == ("resume", str(resume_id))

    await service.cancel(OWNER, resume_id)

    assert uow.store.resumes[resume_id].status is ResumeStatus.CANCELLED
    assert (await service.saved(OWNER)).items == ()
    assert await service.running_jobs(OWNER) == ()


async def test_a_redraft_cancelled_goes_back_to_its_last_version() -> None:
    uow = FakeResumeUnitOfWork()
    service = _service(uow)
    resume_id = await _resume(service)
    await service.save_version(OWNER, resume_id, content=_content())
    uow.store.resumes[resume_id].status = ResumeStatus.READY
    await service.redraft(OWNER, resume_id)

    await service.cancel(OWNER, resume_id)

    stored = uow.store.resumes[resume_id]
    assert stored.status is ResumeStatus.READY
    assert stored.section_plan[:3] == make_content(Bullet("x", ("e1",))).get_plan()
    with pytest.raises(ConflictError):
        await service.cancel(OWNER, resume_id)


async def test_a_second_resume_for_a_target_waits_for_the_first() -> None:
    service = _service(FakeResumeUnitOfWork())
    ref = TargetRef(str(uuid.uuid4()))
    await service.request(OWNER, ref, template="organic", options=Options())

    with pytest.raises(ConflictError):
        await service.request(OWNER, ref, template="organic", options=Options())
