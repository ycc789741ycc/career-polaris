"""Contact details as typed items, each drawn with its icon (ADR 0048)."""

from __future__ import annotations

import re
from dataclasses import replace

import pytest

from advisor.resume.domain import (
    ContactItem,
    ContactKind,
    Options,
    ResumeContent,
    ResumeError,
    Template,
    assert_well_formed,
    get_built_in_spec,
    get_contact_items,
)
from advisor.resume.infra.render import render_html
from tests.unit.advisor.resume.builders import make_content

LINE = (
    "maya@example.com · +49 151 2345 6789 | github.com/mayalin, "
    "linkedin.com/in/mayalin · maya.dev · Berlin, Germany"
)


def test_a_contact_line_is_read_into_typed_items_in_its_order() -> None:
    items = get_contact_items(LINE)

    assert [(i.kind, i.value) for i in items] == [
        (ContactKind.EMAIL, "maya@example.com"),
        (ContactKind.PHONE, "+49 151 2345 6789"),
        (ContactKind.GITHUB, "github.com/mayalin"),
        (ContactKind.LINKEDIN, "linkedin.com/in/mayalin"),
        (ContactKind.WEBSITE, "maya.dev"),
        (ContactKind.LOCATION, "Berlin"),
        (ContactKind.LOCATION, "Germany"),
    ]
    assert get_contact_items("") == ()


def test_a_line_is_cut_to_the_limits() -> None:
    items = get_contact_items(" · ".join(f"place {i}" for i in range(12)))

    assert len(items) == 8


@pytest.mark.parametrize(
    "contacts",
    [
        tuple(ContactItem(ContactKind.LOCATION, f"p{i}") for i in range(9)),
        (ContactItem(ContactKind.EMAIL, " "),),
        (ContactItem(ContactKind.WEBSITE, "x" * 201),),
    ],
)
def test_contact_details_keep_their_limits(contacts: tuple[ContactItem, ...]) -> None:
    with pytest.raises(ResumeError):
        assert_well_formed(replace(make_content(), contacts=contacts))


def test_each_detail_prints_with_its_icon_inline_and_fetches_nothing() -> None:
    content = replace(make_content(), contacts=get_contact_items(LINE))

    html = render_html(content, spec=get_built_in_spec(Template.ORGANIC), options=Options())

    assert html.count('<span class="contact-item"><svg') == 7
    assert "github.com/mayalin" in html
    assert not re.search(r"(?:src|href)=", html)
    assert ResumeContent.from_dict(content.to_dict()) == content
