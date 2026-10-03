"""Résumé templates of the user's own (ADR 0040): a checked spec, kept per user,
drawn by the renderer, never markup."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from advisor.resume import Options, ResumeService, Template
from advisor.resume.domain import (
    BUILT_IN_TEMPLATES,
    Bullet,
    Layout,
    SectionKind,
    TemplateSpec,
    TemplateSpecError,
    get_built_in_spec,
    get_contrast,
)
from advisor.resume.infra.render import render_html
from advisor.target import TargetRef
from kernel.errors import ConflictError, NotFoundError, ValidationError
from tests.unit.advisor.resume.builders import make_content
from tests.unit.advisor.resume.fakes import (
    FakeObjectStore,
    FakeProfile,
    FakeResumeUnitOfWork,
    FakeTarget,
)

OWNER = uuid.UUID("00000000-0000-0000-0000-000000000001")
OTHER = uuid.UUID("00000000-0000-0000-0000-000000000002")
CITED = Bullet("Owned the retry layer for payments-svc", ("e1",))


def _spec(**changes: Any) -> dict[str, Any]:
    return {**TemplateSpec().to_dict(), **changes}


def _service(uow: FakeResumeUnitOfWork, *, template_max: int = 10) -> ResumeService:
    return ResumeService(
        uow,
        target=FakeTarget(),  # type: ignore[arg-type]
        profile=FakeProfile(),  # type: ignore[arg-type]
        assessment=None,  # type: ignore[arg-type]
        gateway=None,  # type: ignore[arg-type]
        object_store=FakeObjectStore(),  # type: ignore[arg-type]
        template_max=template_max,
    )


async def _resume(service: ResumeService, template: str = "organic") -> uuid.UUID:
    ref = TargetRef(str(uuid.uuid4()), None)
    return (await service.request(OWNER, ref, template=template, options=Options())).id


# -- the spec -----------------------------------------------------------------


def test_a_spec_reads_back_what_it_wrote() -> None:
    spec = TemplateSpec(
        layout=Layout.SIDEBAR_LEFT,
        heading_font="DejaVu Serif",
        sidebar_kinds=(SectionKind.SKILLS,),
    )
    assert TemplateSpec.from_dict(spec.to_dict()) == spec


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"heading_font": "Comic Sans"}, "not one the résumé can set"),
        ({"accent_color": "red"}, "not a #rrggbb colour"),
        ({"accent_color": "#fff; }"}, "not a #rrggbb colour"),
        ({"text_color": "#dddddd"}, "too light to read"),
        ({"name_color": "#ffff00"}, "too light to read"),
        ({"body_pt": 14}, "outside"),
        ({"name_pt": 8}, "outside"),
        ({"sidebar_kinds": ["experience"]}, "only lists can sit in the sidebar"),
        ({"sidebar_kinds": ["skills", "skills"]}, "named twice"),
        ({"layout": "three_columns"}, "could not be read"),
    ],
)
def test_a_spec_outside_what_the_renderer_draws_is_refused(
    changes: dict[str, Any], message: str
) -> None:
    with pytest.raises(TemplateSpecError, match=message):
        TemplateSpec.from_dict(_spec(**changes))


def test_the_built_in_templates_are_readable_specs() -> None:
    for built_in in BUILT_IN_TEMPLATES.values():
        assert TemplateSpec.from_dict(built_in.spec.to_dict()) == built_in.spec
    assert get_contrast("#000000") == pytest.approx(21.0)
    assert get_contrast("#ffffff") == pytest.approx(1.0)


# -- the renderer draws each choice -------------------------------------------


def test_a_sidebar_holds_the_lists_it_names_and_the_contact_line() -> None:
    content = make_content(CITED, skills=("Go", "Kafka"))
    spec = TemplateSpec(layout=Layout.SIDEBAR_LEFT, sidebar_kinds=(SectionKind.SKILLS,))
    html = render_html(content, spec=spec, options=Options())

    side = html.index('<div class="side">')
    main = html.index('<div class="main">')
    assert side < html.index('<span class="skill">Go</span>') < main
    assert side < html.index('<div class="contact">') < main
    assert html.index("Owned the retry layer") > main


def test_a_right_sidebar_comes_after_the_main_column() -> None:
    content = make_content(CITED, skills=("Go",))
    spec = TemplateSpec(layout=Layout.SIDEBAR_RIGHT, sidebar_kinds=(SectionKind.SKILLS,))
    html = render_html(content, spec=spec, options=Options())

    assert html.index('<div class="main">') < html.index('<div class="side">')


def test_the_band_headings_and_bullets_follow_the_spec() -> None:
    spec = TemplateSpec(
        layout=Layout.HEADER_BAND,
        heading_case=TemplateSpec().heading_case.AS_WRITTEN,
        bullet=TemplateSpec().bullet.DASH,
        text_color="#333333",
    )
    html = render_html(make_content(CITED), spec=spec, options=Options())

    assert '<header class="band">' in html
    assert f"background: {spec.get_band_color()}" in html
    assert "text-transform: none" in html
    assert 'list-style: "\\2013  "' in html
    assert "color: #333333" in html


@pytest.mark.parametrize("layout", list(Layout))
def test_each_layout_prints_each_section_once(layout: Layout) -> None:
    content = make_content(CITED, skills=("Go", "Kafka"))
    spec = TemplateSpec(layout=layout, sidebar_kinds=(SectionKind.SKILLS,))
    html = render_html(content, spec=spec, options=Options())

    for heading in ("Summary", "Experience", "Skills"):
        assert html.count(f"<h2>{heading}</h2>") == 1
    assert html.count('<div class="contact">') == 1


def test_the_css_holds_only_checked_values() -> None:
    """A spec reaches the CSS only after ``from_dict`` checked it; anything
    that would close a rule is refused before it gets there."""
    for value in ("#c67139; } body { display: none", "url(http://x)", "red"):
        with pytest.raises(TemplateSpecError):
            TemplateSpec.from_dict(_spec(accent_color=value))
    with pytest.raises(TemplateSpecError):
        TemplateSpec.from_dict(_spec(heading_font='Figtree", x'))


def test_a_band_is_a_light_tint_of_the_accent() -> None:
    assert TemplateSpec(accent_color="#c67139").get_band_color() == "#f8ede6"


# -- keeping templates of your own ----------------------------------------------


async def test_a_template_of_your_own_is_listed_after_the_built_in_ones() -> None:
    service = _service(FakeResumeUnitOfWork())
    first = await service.create_template(OWNER, name="  Mine   one ", spec=_spec())
    second = await service.create_template(OWNER, name="Mine two", spec=_spec(layout="header_band"))

    listed = (await service.templates(OWNER)).items
    assert [t.id for t in listed] == ["organic", "plain", first.id, second.id]
    assert (listed[2].name, listed[2].is_built_in) == ("Mine one", False)
    assert [t.id for t in (await service.templates(OTHER)).items] == ["organic", "plain"]


async def test_a_template_with_a_value_out_of_range_is_refused() -> None:
    service = _service(FakeResumeUnitOfWork())
    with pytest.raises(ValidationError, match="too light"):
        await service.create_template(OWNER, name="Faint", spec=_spec(text_color="#eeeeee"))
    with pytest.raises(ValidationError, match="needs a name"):
        await service.create_template(OWNER, name="   ", spec=_spec())


async def test_only_so_many_templates_are_kept() -> None:
    service = _service(FakeResumeUnitOfWork(), template_max=1)
    await service.create_template(OWNER, name="One", spec=_spec())
    with pytest.raises(ConflictError, match="1 templates of your own"):
        await service.create_template(OWNER, name="Two", spec=_spec())


async def test_a_resume_set_in_your_template_exports_its_look() -> None:
    uow = FakeResumeUnitOfWork()
    service = _service(uow)
    mine = await service.create_template(OWNER, name="Mine", spec=_spec(accent_color="#2a6f97"))
    resume_id = await _resume(service, template=mine.id)
    await service.save_version(OWNER, resume_id, content=make_content(CITED).to_dict())

    assert (await service.get(OWNER, resume_id)).template == mine.id
    first = await service.request_export(OWNER, resume_id, number=1)
    assert first.template is None
    assert uow.store.exports[first.id].spec == mine.spec.to_dict()


async def test_editing_a_template_renders_its_resumes_again_on_export() -> None:
    uow = FakeResumeUnitOfWork()
    service = _service(uow)
    mine = await service.create_template(OWNER, name="Mine", spec=_spec())
    resume_id = await _resume(service, template=mine.id)
    await service.save_version(OWNER, resume_id, content=make_content(CITED).to_dict())
    first = await service.request_export(OWNER, resume_id, number=1)
    await service.export(OWNER, first.id)

    assert (await service.request_export(OWNER, resume_id, number=1)).id == first.id
    await service.update_template(OWNER, uuid.UUID(mine.id), name="Mine", spec=_spec(bullet="dash"))
    again = await service.request_export(OWNER, resume_id, number=1)

    assert again.id != first.id
    assert uow.store.exports[first.id].spec == mine.spec.to_dict()


async def test_deleting_a_template_moves_its_resumes_to_organic() -> None:
    uow = FakeResumeUnitOfWork()
    service = _service(uow)
    mine = await service.create_template(OWNER, name="Mine", spec=_spec())
    resume_id = await _resume(service, template=mine.id)

    await service.delete_template(OWNER, uuid.UUID(mine.id))

    assert (await service.get(OWNER, resume_id)).template == "organic"
    assert uow.store.templates == {}


async def test_a_template_must_be_built_in_or_your_own() -> None:
    service = _service(FakeResumeUnitOfWork())
    resume_id = await _resume(service)
    theirs = await service.create_template(OTHER, name="Theirs", spec=_spec())

    with pytest.raises(NotFoundError):
        await service.update_settings(OWNER, resume_id, template=theirs.id, options=Options())
    with pytest.raises(ValidationError, match="no such template"):
        await service.update_settings(OWNER, resume_id, template="fancy", options=Options())
    with pytest.raises(NotFoundError):
        await service.delete_template(OWNER, uuid.UUID(theirs.id))

    await service.update_settings(OWNER, resume_id, template="plain", options=Options())
    assert (await service.get(OWNER, resume_id)).template == str(Template.PLAIN)
    assert get_built_in_spec(Template.PLAIN).rule_color == "#cfcac5"
