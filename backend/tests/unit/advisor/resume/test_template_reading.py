"""Starting a template from a file (ADR 0041): a PDF's style read locally into
a draft spec, with nothing of its text kept, and the file deleted."""

from __future__ import annotations

import uuid
from dataclasses import fields

import pytest

from advisor.resume import ResumeService
from advisor.resume.domain import (
    Bullet,
    BulletStyle,
    FontKind,
    HeadingCase,
    Layout,
    Options,
    SectionKind,
    StyleRun,
    TemplateReadingError,
    TemplateSpec,
    get_font_kind,
    get_template_spec_from_runs,
)
from advisor.resume.infra.render import render_html, render_pdf
from advisor.resume.infra.style_reader import read_style_runs
from kernel.errors import NotFoundError, ValidationError
from tests.unit.advisor.resume.builders import make_content
from tests.unit.advisor.resume.fakes import (
    FakeObjectStore,
    FakeProfile,
    FakeResumeUnitOfWork,
    FakeTarget,
)

OWNER = uuid.UUID("00000000-0000-0000-0000-000000000001")
OTHER = uuid.UUID("00000000-0000-0000-0000-000000000002")
PAGE = 595.0
SECRET = "Maya Lin Chen"


def run(
    size: float,
    *,
    x: float = 48,
    y: float = 700,
    font: str = "/ABCDEF+Figtree",
    color: str = "#201e1d",
    length: int = 40,
    is_upper: bool = False,
    marker: BulletStyle | None = None,
) -> StyleRun:
    return StyleRun(
        font_name=font,
        size_pt=size,
        color=color,
        x=x,
        y=y,
        length=length,
        is_upper=is_upper,
        marker=marker,
    )


def one_column() -> list[StyleRun]:
    return [
        run(24, font="/X+Garamond-Bold", color="#1b3a5c", length=13),
        run(9, color="#1b3a5c", length=10, is_upper=True, font="/X+Helvetica-Bold"),
        *(run(10.5, length=60) for _ in range(8)),
        *(run(10.5, color="#2a6f97", length=1, marker=BulletStyle.DASH) for _ in range(4)),
    ]


def pdf_of(spec: TemplateSpec) -> bytes:
    content = make_content(
        Bullet("Owned the retry layer for payments-svc at scale", ("e1",)),
        Bullet("Cut p99 latency by 70 percent across checkout", ("e1",)),
        name=SECRET,
        skills=("Go", "Kafka", "Postgres", "Redis"),
    )
    return render_pdf(render_html(content, spec=spec, options=Options()))


def values_of(item: StyleRun) -> list[object]:
    return [getattr(item, f.name) for f in fields(item)]


# -- the rule -------------------------------------------------------------------


def test_name_heading_and_body_come_out_in_their_order() -> None:
    spec = get_template_spec_from_runs(one_column(), page_width=PAGE).spec

    assert (spec.name_pt, spec.heading_pt, spec.body_pt) == (24.0, 9.0, 10.5)
    assert spec.layout is Layout.SINGLE_COLUMN
    assert spec.heading_case is HeadingCase.UPPER
    assert spec.bullet is BulletStyle.DASH
    assert (spec.name_color, spec.accent_color) == ("#1b3a5c", "#2a6f97")
    assert (spec.heading_font, spec.body_font) == ("DejaVu Serif", "Figtree")


@pytest.mark.parametrize(("sidebar_x", "layout"), [(40, "sidebar_left"), (420, "sidebar_right")])
def test_two_columns_of_runs_are_a_sidebar_on_its_side(sidebar_x: float, layout: str) -> None:
    main_x = 200 if sidebar_x < 200 else 40
    runs = [
        run(22, length=13),
        *(run(10, x=sidebar_x, length=12) for _ in range(5)),
        *(run(10, x=main_x, length=60) for _ in range(10)),
    ]
    draft = get_template_spec_from_runs(runs, page_width=PAGE)

    assert str(draft.spec.layout) == layout
    assert draft.spec.sidebar_kinds == (SectionKind.SKILLS,)
    assert "sidebar_kinds" in draft.defaulted


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("/ABCDEF+EBGaramond-Regular", FontKind.SERIF),
        ("/X+TimesNewRomanPSMT", FontKind.SERIF),
        ("/X+SourceSansPro-Bold", FontKind.SANS),
        ("/X+Helvetica", FontKind.SANS),
        ("/X+JetBrainsMono-Regular", FontKind.MONO),
        ("/X+CourierNewPSMT", FontKind.MONO),
        ("/X+PlayfairDisplay-Bold", FontKind.DISPLAY),
        ("", None),
    ],
)
def test_font_names_map_to_a_kind(name: str, kind: FontKind | None) -> None:
    assert get_font_kind(name) is kind


def test_what_cannot_be_read_takes_organic_and_is_flagged() -> None:
    # One size, black only, no font name, no markers: little to go on.
    draft = get_template_spec_from_runs(
        [run(10, font="", length=50) for _ in range(6)], page_width=PAGE
    )
    organic = TemplateSpec()

    for name in ("name_pt", "heading_pt", "accent_color", "heading_font", "body_font", "bullet"):
        assert name in draft.defaulted
        assert getattr(draft.spec, name) == getattr(organic, name)
    assert set(draft.read) | set(draft.defaulted) == {f.name for f in fields(TemplateSpec)}


def test_a_value_out_of_range_or_too_light_is_brought_into_line() -> None:
    runs = [
        run(48, color="#eeeeee", length=10),
        *(run(7, length=60) for _ in range(3)),
    ]
    draft = get_template_spec_from_runs(runs, page_width=PAGE)

    assert (draft.spec.name_pt, draft.spec.body_pt) == (30.0, 8.5)
    assert "name_color" in draft.defaulted


def test_a_page_with_no_runs_is_unreadable() -> None:
    with pytest.raises(TemplateReadingError):
        get_template_spec_from_runs([], page_width=PAGE)


# -- the reader, on real PDFs -----------------------------------------------------


@pytest.mark.parametrize(
    "spec",
    [
        TemplateSpec(),
        TemplateSpec(
            layout=Layout.SIDEBAR_LEFT,
            sidebar_kinds=(SectionKind.SKILLS,),
            heading_font="DejaVu Serif",
            accent_color="#2a6f97",
            rule_color="#2a6f97",
            bullet=BulletStyle.DASH,
            heading_case=HeadingCase.AS_WRITTEN,
        ),
        TemplateSpec(layout=Layout.SIDEBAR_RIGHT, sidebar_kinds=(SectionKind.SKILLS,)),
    ],
    ids=["one-column", "sidebar-left", "sidebar-right"],
)
def test_a_pdf_we_rendered_reads_back_as_its_spec(spec: TemplateSpec) -> None:
    runs, width = read_style_runs(pdf_of(spec), max_pages=3)
    draft = get_template_spec_from_runs(runs, page_width=width)

    assert {name: getattr(draft.spec, name) for name in draft.read} == {
        name: getattr(spec, name) for name in draft.read
    }
    assert {"layout", "name_pt", "body_pt", "accent_color", "heading_case"} <= set(draft.read)


def test_runs_carry_no_text() -> None:
    runs, _width = read_style_runs(pdf_of(TemplateSpec()), max_pages=3)

    assert runs
    assert not any("Maya" in str(value) for r in runs for value in values_of(r))


def test_a_page_with_no_text_reads_as_unreadable() -> None:
    runs, width = read_style_runs(
        render_pdf("<!doctype html><html><body></body></html>"), max_pages=3
    )

    with pytest.raises(TemplateReadingError):
        get_template_spec_from_runs(runs, page_width=width)


# -- the service ------------------------------------------------------------------


def service(store: FakeObjectStore, uow: FakeResumeUnitOfWork) -> ResumeService:
    return ResumeService(
        uow,
        target=FakeTarget(),  # type: ignore[arg-type]
        profile=FakeProfile(),  # type: ignore[arg-type]
        assessment=None,  # type: ignore[arg-type]
        gapfill=None,  # type: ignore[arg-type]
        gateway=None,  # type: ignore[arg-type]
        object_store=store,  # type: ignore[arg-type]
        template_upload_max_bytes=2_000_000,
    )


async def test_a_file_is_read_into_a_draft_and_then_deleted() -> None:
    store, uow = FakeObjectStore(), FakeResumeUnitOfWork()
    resumes = service(store, uow)
    reading = await resumes.upload_template_file(
        OWNER, content_type="application/pdf", content=pdf_of(TemplateSpec())
    )
    assert reading.status == "reading" and len(store.objects) == 1

    await resumes.read_template(OWNER, reading.id)

    ready = await resumes.template_reading(OWNER, reading.id)
    assert ready.status == "ready" and ready.spec is not None
    assert store.objects == {}
    stored = uow.store.readings[reading.id]
    assert stored.storage_key is None
    assert "Maya" not in repr(stored)
    with pytest.raises(NotFoundError):
        await resumes.template_reading(OTHER, reading.id)


async def test_an_unreadable_file_fails_and_is_deleted_too() -> None:
    store, uow = FakeObjectStore(), FakeResumeUnitOfWork()
    resumes = service(store, uow)
    reading = await resumes.upload_template_file(
        OWNER, content_type="application/pdf", content=b"%PDF-1.4 not really"
    )

    await resumes.read_template(OWNER, reading.id)

    failed = await resumes.template_reading(OWNER, reading.id)
    assert (failed.status, failed.error_code) == ("failed", "unreadable_file")
    assert store.objects == {}


@pytest.mark.parametrize(
    ("content_type", "content", "message"),
    [
        ("application/pdf", b"x" * 2_000_001, "larger than we accept"),
        ("text/plain", b"hello", "only from a PDF"),
        ("application/pdf", b"   ", "empty"),
    ],
)
async def test_an_upload_outside_the_limits_is_refused_before_it_is_stored(
    content_type: str, content: bytes, message: str
) -> None:
    store, uow = FakeObjectStore(), FakeResumeUnitOfWork()
    with pytest.raises(ValidationError, match=message):
        await service(store, uow).upload_template_file(
            OWNER, content_type=content_type, content=content
        )
    assert store.objects == {} and uow.store.readings == {}


async def test_a_reading_is_forgotten_with_its_draft() -> None:
    store, uow = FakeObjectStore(), FakeResumeUnitOfWork()
    resumes = service(store, uow)
    reading = await resumes.upload_template_file(
        OWNER, content_type="application/pdf", content=pdf_of(TemplateSpec())
    )

    await resumes.forget_template_reading(OWNER, reading.id)

    assert uow.store.readings == {} and store.objects == {}
