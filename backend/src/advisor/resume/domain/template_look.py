"""How each résumé template looks, as data (ADR 0038).

One definition, read by the PDF renderer and served to the SPA's preview, so
the two cannot drift. A look is a few checked values — a rule, the name
colour, the bullet colour, two font families — never markup: every value goes
into the PDF's CSS from here, and nothing a user writes does.
"""

from __future__ import annotations

from dataclasses import dataclass

from advisor.resume.domain.constants import BODY_FONT, HEADING_FONT
from advisor.resume.domain.content import Template


@dataclass(frozen=True, slots=True)
class TemplateLook:
    template: Template
    name: str
    note: str
    # The line under the header, as a CSS border: width, style, colour.
    rule: str
    # The template's accent, for its swatch in the picker.
    swatch: str
    name_color: str
    dot_color: str
    heading_font: str = HEADING_FONT
    body_font: str = BODY_FONT


# The prototype's two templates: Organic and Plain.
TEMPLATE_LOOKS: dict[Template, TemplateLook] = {
    Template.ORGANIC: TemplateLook(
        template=Template.ORGANIC,
        name="Organic",
        note="Rounded, terracotta rule.",
        rule="3px solid #c67139",
        swatch="#c67139",
        name_color="#8a4a20",
        dot_color="#c67139",
    ),
    Template.PLAIN: TemplateLook(
        template=Template.PLAIN,
        name="Plain",
        note="One page, evidence first.",
        rule="1px solid #cfcac5",
        swatch="#9b9691",
        name_color="#201e1d",
        dot_color="#9b9691",
    ),
}


def get_template_look(template: Template) -> TemplateLook:
    return TEMPLATE_LOOKS[template]
