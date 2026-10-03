"""Résumé content rules, requirement coverage, and export rendering."""

from __future__ import annotations

import io
from typing import Any

import pytest
from pypdf import PdfReader

from advisor.resume.domain import (
    TRIMMED_SKILLS,
    Bullet,
    Options,
    Origin,
    ResumeContent,
    ResumeError,
    Template,
    Verdict,
    assert_well_formed,
    assert_written_lines_cited,
    coverage,
    get_built_in_spec,
    get_download_name,
    mark_edits,
    settle_revision,
)
from advisor.resume.infra.render import render_html, render_pdf
from tests.unit.advisor.resume.builders import get_lines, make_content


def content(*bullets: Bullet, name: str = "Maya Lin Chen") -> ResumeContent:
    return make_content(*bullets, name=name)


CITED = Bullet("Owned the retry layer for payments-svc", ("e1",))
ORGANIC = get_built_in_spec(Template.ORGANIC)


# -- the rules ------------------------------------------------------------


def test_content_survives_being_stored() -> None:
    original = content(CITED, Bullet("My own line", (), Origin.YOURS, answers="Lead"))
    assert ResumeContent.from_dict(original.to_dict()) == original


def test_a_written_line_must_cite_evidence() -> None:
    with pytest.raises(ResumeError, match="cites no evidence"):
        assert_written_lines_cited(content(CITED, Bullet("Led everything")))


def test_a_line_the_user_wrote_may_stand_uncited() -> None:
    assert_written_lines_cited(content(CITED, Bullet("Led the guild", (), Origin.YOURS)))


def test_a_resume_needs_a_name_and_no_empty_lines() -> None:
    with pytest.raises(ResumeError, match="name"):
        assert_well_formed(content(CITED, name=" "))
    with pytest.raises(ResumeError, match="empty line"):
        assert_well_formed(content(Bullet("  ", ("e1",))))


def test_an_edited_line_becomes_the_users_and_an_untouched_one_keeps_its_source() -> None:
    before = content(CITED, Bullet("Cut p99 latency by 40%", ("e2",)))
    edited = content(CITED, Bullet("Cut p99 latency by 40% across checkout", ("e2",)))

    settled = mark_edits(before, edited)

    kept, changed = get_lines(settled)
    assert kept == CITED
    assert changed.origin is Origin.YOURS
    assert changed.evidence_ids == ("e2",)


def test_a_proposal_cannot_relabel_the_users_own_line() -> None:
    mine = Bullet("Ran the incident guild", (), Origin.YOURS)
    proposed = content(
        Bullet(mine.text, ("e9",), Origin.WRITTEN),
        Bullet("Answered their top requirement first", ("e1",), Origin.YOURS),
    )

    settled = settle_revision(content(mine), proposed, lambda cited: cited)

    kept, new = get_lines(settled)
    assert kept == mine, "an unchanged line is the line it was"
    assert new.origin is Origin.WRITTEN, "new text is the model's, whatever it claims"


def test_only_a_proposals_new_lines_have_their_citations_resolved() -> None:
    """An unchanged line keeps its stored ids; a new one cites what the prompt showed."""
    proposed = content(
        Bullet(CITED.text, ("E1",)),
        Bullet("Answered their top requirement first", ("E1", "E2")),
    )
    ids = {"E1": "e1", "E2": "e2"}

    settled = settle_revision(content(CITED), proposed, lambda cited: tuple(ids[c] for c in cited))

    kept, new = get_lines(settled)
    assert kept == CITED
    assert new.evidence_ids == ("e1", "e2")


def test_citations_can_be_renamed_throughout() -> None:
    renamed = content(CITED).with_citations(lambda ids: tuple(i.upper() for i in ids))
    assert renamed.cited() == {"E1"}
    assert get_lines(renamed)[0].text == CITED.text


# -- coverage -------------------------------------------------------------


def test_coverage_is_decided_by_score_against_the_bar() -> None:
    rows = coverage(
        requirements=["Leads", "Reliable", "Mentors", "Kubernetes", "Unscored"],
        requirement_map={
            "Leads": "lead",
            "Reliable": "rel",
            "Mentors": "mentor",
            "Kubernetes": None,
            "Unscored": "craft",
        },
        scores={"lead": 70, "rel": 75, "mentor": 50, "craft": 90},
        targets={"lead": 83, "rel": 60, "mentor": 80},
        evidence={"lead": ["e1"], "rel": ["e2"]},
    )
    assert [(r.requirement, r.verdict) for r in rows] == [
        ("Leads", Verdict.PARTIAL),  # 13 short: within 14
        ("Reliable", Verdict.COVERED),
        ("Mentors", Verdict.GAP),
        ("Kubernetes", Verdict.GAP),  # maps to nothing: no evidence at all
        ("Unscored", Verdict.GAP),  # the Target sets no bar for it
    ]
    assert rows[1].evidence_ids == ("e2",)
    assert rows[3].evidence_ids == ()


def test_fourteen_short_is_no_longer_partial() -> None:
    [row] = coverage(
        requirements=["Leads"],
        requirement_map={"Leads": "lead"},
        scores={"lead": 66},
        targets={"lead": 80},
        evidence={},
    )
    assert row.verdict is Verdict.GAP


# -- export ---------------------------------------------------------------


def test_every_value_is_escaped_in_the_export() -> None:
    hostile = content(Bullet('<script>alert("x")</script>', ("e1",)), name="<b>Maya</b>")
    html = render_html(hostile, spec=get_built_in_spec(Template.ORGANIC), options=Options())
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "<b>Maya</b>" not in html


def test_trim_keeps_three_lines_a_role() -> None:
    long = content(*(Bullet(f"Line {i}", ("e1",)) for i in range(6)))
    html = render_html(long, spec=get_built_in_spec(Template.PLAIN), options=Options(trim=True))
    assert "Line 2" in html
    assert "Line 3" not in html


def test_each_template_has_its_own_rule() -> None:
    organic = render_html(
        content(CITED), spec=get_built_in_spec(Template.ORGANIC), options=Options()
    )
    plain = render_html(content(CITED), spec=get_built_in_spec(Template.PLAIN), options=Options())
    assert "3px solid #c67139" in organic and "#c67139" not in plain
    assert "1px solid #cfcac5" in plain


def test_the_prototype_offers_two_templates() -> None:
    assert [str(t) for t in Template] == ["organic", "plain"]


def test_the_export_is_a_pdf_rendered_without_fetching_anything() -> None:
    pdf = render_pdf(render_html(content(CITED), spec=ORGANIC, options=Options()))
    assert pdf.startswith(b"%PDF-")


def test_an_export_that_tries_to_fetch_something_is_refused() -> None:
    # render_html never emits a URL; this is the guard behind that.
    with pytest.raises(ValueError, match="does not fetch"):
        render_pdf('<img src="http://169.254.169.254/latest/meta-data">')


# -- one look, read by the PDF and the preview (ADR 0038) ----------------------


def test_the_export_sets_type_in_the_design_systems_fonts_with_a_fallback() -> None:
    html = render_html(content(CITED), spec=ORGANIC, options=Options())

    assert '"Caprasimo", "DejaVu Sans", serif' in html
    assert '"Figtree", "DejaVu Sans", sans-serif' in html


@pytest.mark.parametrize("template", list(Template))
def test_each_template_is_drawn_from_its_look(template: Template) -> None:
    spec = get_built_in_spec(template)
    html = render_html(content(CITED), spec=spec, options=Options())

    assert f"border-bottom: {spec.get_rule_css()}" in html
    assert f"color: {spec.name_color}" in html
    assert f"li::marker {{ color: {spec.accent_color}; }}" in html


def test_trim_cuts_skills_by_the_shared_limit_too() -> None:
    many = make_content(CITED, skills=tuple(f"Skill {i}" for i in range(20)))
    html = render_html(many, spec=get_built_in_spec(Template.PLAIN), options=Options(trim=True))

    assert f"Skill {TRIMMED_SKILLS - 1}<" in html and f"Skill {TRIMMED_SKILLS}<" not in html


def test_the_pdf_embeds_the_bundled_fonts() -> None:
    """The fonts are installed in the image this runs in, as in the worker's,
    and fontconfig matches them by the family names the CSS asks for."""
    pdf = render_pdf(render_html(content(CITED), spec=ORGANIC, options=Options()))

    embedded: set[str] = set()
    for page in PdfReader(io.BytesIO(pdf)).pages:
        resources: Any = page["/Resources"]
        for font in resources["/Font"].values():
            embedded.add(str(font.get_object()["/BaseFont"]).split("+")[-1])
    # The headings' 800 weight embeds as a second Figtree face.
    assert {"Caprasimo", "Figtree"} <= embedded
    assert any(font.startswith("Figtree-") for font in embedded)
    assert not any(font.startswith("DejaVu") for font in embedded)


@pytest.mark.parametrize(
    ("name", "label", "saved_as"),
    [
        ("Maya Chen", "Staff Engineer · Northwind", "Maya Chen — Staff Engineer · Northwind.pdf"),
        ("", "Staff Engineer", "Staff Engineer.pdf"),
        ('A/B "C"', "", "A B C.pdf"),
        ("", "", "Résumé.pdf"),
    ],
)
def test_a_download_is_named_for_the_person_and_the_role(
    name: str, label: str, saved_as: str
) -> None:
    assert get_download_name(name, label) == saved_as
