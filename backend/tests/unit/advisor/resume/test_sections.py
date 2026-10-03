"""A résumé's sections (ADR 0039): which there may be, what each holds, how
each prints, and how a plan lays content out."""

from __future__ import annotations

import pytest

from advisor.resume.domain import (
    DEFAULT_PLAN,
    Bullet,
    Entry,
    Options,
    Origin,
    ResumeContent,
    ResumeError,
    Section,
    SectionKind,
    SectionSlot,
    Template,
    assert_plan_valid,
    assert_well_formed,
    assert_written_lines_cited,
    get_planned,
)
from advisor.resume.infra.render import render_html
from tests.unit.advisor.resume.builders import make_content

CITED = Bullet("Owned the retry layer for payments-svc", ("e1",))


def _with(*sections: Section) -> ResumeContent:
    base = make_content(CITED)
    return ResumeContent(base.name, base.headline, base.contact, (*base.sections, *sections))


MINE = Bullet("Mentors at a code club", (), Origin.YOURS)
EVERY_KIND = (
    Section(
        SectionKind.SIDE_PROJECTS,
        entries=(Entry("ledger-sim", "", "2025", "github.com/m/l", (CITED,)),),
    ),
    Section(SectionKind.OPEN_SOURCE, entries=(Entry("pgx", "", "2024", "", (CITED,)),)),
    Section(SectionKind.EDUCATION, entries=(Entry("BSc Computer Science", "TU Berlin", "2016"),)),
    Section(
        SectionKind.TALKS_AND_WRITING, entries=(Entry("Idempotency keys", "GopherCon", "2025"),)
    ),
    Section(SectionKind.CERTIFICATIONS, items=("CKA",)),
    Section(SectionKind.CUSTOM, title="Volunteering", bullets=(MINE,)),
)
EXPERIENCE = SectionSlot(SectionKind.EXPERIENCE)
SKILLS = SectionSlot(SectionKind.SKILLS)


def test_every_kind_survives_being_stored() -> None:
    content = _with(*EVERY_KIND)

    assert_well_formed(content)
    assert ResumeContent.from_dict(content.to_dict()) == content


def test_the_default_plan_is_the_three_sections_every_resume_had() -> None:
    assert [s.kind for s in DEFAULT_PLAN] == [
        SectionKind.SUMMARY,
        SectionKind.EXPERIENCE,
        SectionKind.SKILLS,
    ]
    assert make_content(CITED).get_plan() == DEFAULT_PLAN


@pytest.mark.parametrize(
    ("plan", "match"),
    [
        ((SectionSlot(SectionKind.SUMMARY),), "experience"),
        ((EXPERIENCE, EXPERIENCE), "experience"),
        ((EXPERIENCE, SKILLS, SKILLS), "one skills"),
        ((EXPERIENCE, SectionSlot(SectionKind.CUSTOM)), "heading"),
        (
            (EXPERIENCE, *(SectionSlot(SectionKind.CUSTOM, f"Own {i}") for i in range(4))),
            "at most 3",
        ),
        (
            (
                EXPERIENCE,
                SectionSlot(SectionKind.CUSTOM, "Volunteering"),
                SectionSlot(SectionKind.CUSTOM, "volunteering"),
            ),
            "same heading",
        ),
    ],
)
def test_a_plan_keeps_its_rules(plan: tuple[SectionSlot, ...], match: str) -> None:
    with pytest.raises(ResumeError, match=match):
        assert_plan_valid(plan)


def test_experience_can_move_but_not_go() -> None:
    moved = (SectionSlot(SectionKind.EXPERIENCE), SectionSlot(SectionKind.SUMMARY))
    assert_plan_valid(moved)
    with pytest.raises(ResumeError, match="experience"):
        assert_plan_valid((SectionSlot(SectionKind.SUMMARY), SectionSlot(SectionKind.SKILLS)))


@pytest.mark.parametrize(
    "section",
    [
        Section(
            SectionKind.SIDE_PROJECTS, entries=(Entry("ledger-sim", bullets=(Bullet("Built it"),)),)
        ),
        Section(SectionKind.CUSTOM, title="Volunteering", bullets=(Bullet("Ran a meetup"),)),
    ],
)
def test_a_written_line_cites_evidence_in_any_section(section: Section) -> None:
    with pytest.raises(ResumeError, match="cites no evidence"):
        assert_written_lines_cited(_with(section))


def test_a_section_keeps_its_shapes_limits() -> None:
    many = Section(SectionKind.CERTIFICATIONS, items=tuple(f"C{i}" for i in range(31)))
    with pytest.raises(ResumeError, match="at most 30 items"):
        assert_well_formed(_with(many))
    with pytest.raises(ResumeError, match="no title"):
        assert_well_formed(_with(Section(SectionKind.EDUCATION, entries=(Entry(" "),))))
    long_link = Section(SectionKind.OPEN_SOURCE, entries=(Entry("pgx", link="x" * 201),))
    with pytest.raises(ResumeError, match="link"):
        assert_well_formed(_with(long_link))


def test_content_is_laid_out_as_its_plan() -> None:
    content = make_content(CITED)
    plan = (
        SectionSlot(SectionKind.EXPERIENCE),
        SectionSlot(SectionKind.EDUCATION),
        SectionSlot(SectionKind.SUMMARY),
    )

    planned = get_planned(content, plan)

    assert planned.get_plan() == plan
    education = planned.sections[1]
    assert education.kind is SectionKind.EDUCATION and education.is_empty
    assert planned.sections[0] == content.sections[1]


def test_each_kind_prints_under_its_heading_and_an_empty_one_not_at_all() -> None:
    html = render_html(
        _with(*EVERY_KIND, Section(SectionKind.CUSTOM, title="Awards")),
        template=Template.ORGANIC,
        options=Options(),
    )

    for heading in (
        "Side projects",
        "Open source",
        "Education",
        "Talks &amp; writing",
        "Certifications",
        "Volunteering",
    ):
        assert f"<h2>{heading}</h2>" in html
    assert "github.com/m/l" in html and "<a " not in html
    assert "Awards" not in html


def test_trim_cuts_every_shape_by_the_shared_limits() -> None:
    lines = tuple(Bullet(f"Line {i}", ("e1",)) for i in range(5))
    content = _with(Section(SectionKind.CUSTOM, title="Volunteering", bullets=lines))

    html = render_html(content, template=Template.PLAIN, options=Options(trim=True))

    assert "Line 2" in html and "Line 3" not in html
