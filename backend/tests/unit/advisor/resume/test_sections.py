"""A résumé's sections (ADR 0039, ADR 0043): which there may be, which are
shown, what each holds, how each prints, and how a plan lays content out."""

from __future__ import annotations

import pytest

from advisor.resume.domain import (
    BUILT_IN_KINDS,
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
    get_built_in_spec,
    get_full_plan,
    get_planned,
    get_proposal_layout,
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


def test_a_new_resume_holds_every_kind_and_shows_the_three_every_resume_had() -> None:
    assert {s.kind for s in DEFAULT_PLAN} == set(BUILT_IN_KINDS)
    assert [s.kind for s in DEFAULT_PLAN if s.is_shown] == [
        SectionKind.SUMMARY,
        SectionKind.EXPERIENCE,
        SectionKind.SKILLS,
    ]
    assert_plan_valid(DEFAULT_PLAN)


def test_a_slot_is_the_same_section_shown_or_hidden() -> None:
    assert SKILLS == SKILLS.update_shown(False)
    assert SKILLS in (SKILLS.update_shown(False),)
    assert SectionSlot.from_dict(SKILLS.update_shown(False).to_dict()).is_shown is False


def test_a_full_plan_appends_the_kinds_it_lacks_hidden() -> None:
    plan = get_full_plan((SKILLS, EXPERIENCE))

    assert plan[:2] == (SKILLS, EXPERIENCE)
    assert {s.kind for s in plan} == set(BUILT_IN_KINDS)
    assert all(not s.is_shown for s in plan[2:])
    assert get_full_plan(plan) == plan


def test_experience_is_never_hidden() -> None:
    with pytest.raises(ResumeError, match="shows its experience"):
        assert_plan_valid((EXPERIENCE.update_shown(False), SKILLS))
    assert_plan_valid((EXPERIENCE, SKILLS.update_shown(False)))


def test_only_shown_sections_count_toward_the_limit() -> None:
    custom = tuple(SectionSlot(SectionKind.CUSTOM, f"Own {i}") for i in range(3))
    every = (*get_full_plan((EXPERIENCE,)), *custom)
    shown = tuple(s.update_shown(True) for s in every)

    assert_plan_valid(every)
    with pytest.raises(ResumeError, match="shows at most 9"):
        assert_plan_valid(shown)


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


def test_a_plan_shows_and_hides_the_content_it_lays_out() -> None:
    content = make_content(CITED)

    planned = get_planned(content, (EXPERIENCE, SKILLS.update_shown(False)))

    assert [s.is_shown for s in planned.sections] == [True, False]
    assert planned.sections[1].items == ("Go", "Postgres")
    assert [s.kind for s in planned.get_shown().sections] == [SectionKind.EXPERIENCE]


def test_a_proposal_keeps_each_sections_state_unless_it_set_one() -> None:
    volunteering = SectionSlot(SectionKind.CUSTOM, "Volunteering")
    hidden = {SectionKind.SKILLS, SectionKind.CERTIFICATIONS}
    plan = tuple(s.update_shown(s.kind not in hidden) for s in (*get_full_plan(()), volunteering))
    current = get_planned(_with(*EVERY_KIND), plan)
    # The reply rewrote skills, leaving its state alone, and certifications,
    # which the person asked to show; it left every other section out.
    proposed = ResumeContent(
        current.name,
        current.headline,
        current.contact,
        (
            Section(SectionKind.EXPERIENCE, entries=current.sections[1].entries),
            Section(SectionKind.SKILLS, items=("Go",)),
            Section(SectionKind.CERTIFICATIONS, items=("CKA",)),
        ),
    )

    laid_out = get_proposal_layout(current, proposed, [None, None, True])

    states = {s.slot: s.is_shown for s in laid_out.sections}
    assert states[SKILLS] is False
    assert states[SectionSlot(SectionKind.CERTIFICATIONS)] is True
    assert states[EXPERIENCE] is True
    # A built-in section left out is kept as it was; the person's own goes.
    assert {s.kind for s in laid_out.sections} == set(BUILT_IN_KINDS)
    assert volunteering not in states


def test_a_hidden_section_is_kept_and_never_printed() -> None:
    content = get_planned(
        _with(*EVERY_KIND),
        (
            EXPERIENCE,
            SectionSlot(SectionKind.EDUCATION, is_shown=False),
            SectionSlot(SectionKind.CERTIFICATIONS),
        ),
    )

    html = render_html(content, spec=get_built_in_spec(Template.ORGANIC), options=Options())

    assert "<h2>Certifications</h2>" in html
    assert "Education" not in html and "TU Berlin" not in html
    assert ResumeContent.from_dict(content.to_dict()) == content


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
        spec=get_built_in_spec(Template.ORGANIC),
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

    html = render_html(content, spec=get_built_in_spec(Template.PLAIN), options=Options(trim=True))

    assert "Line 2" in html and "Line 3" not in html
