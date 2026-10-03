"""How a résumé template looks, as checked values (ADR 0038, ADR 0040).

A template is a ``TemplateSpec``: a layout, two fonts, four colours, three
sizes, which list sections a sidebar holds, how headings are set, and the
bullet. Never markup. Every value is limited to what both the PDF renderer
and the SPA's preview implement, so the renderer's CSS is built only from
checked enums, numbers and colours, and nothing a user writes reaches it.

The two templates the prototype offers, Organic and Plain, are specs like any
other; a user can keep their own (``CustomTemplate``).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from advisor.resume.domain.constants import (
    BODY_FONT,
    BODY_PT,
    BODY_PT_RANGE,
    HEADING_FONT,
    HEADING_PT,
    HEADING_PT_RANGE,
    MIN_CONTRAST,
    NAME_PT,
    NAME_PT_RANGE,
    TEMPLATE_FONTS,
)
from advisor.resume.domain.content import Template
from advisor.resume.domain.section import SHAPES, SectionKind, SectionShape


class TemplateSpecError(ValueError):
    """A spec with a value outside what the renderer and the preview draw."""


class Layout(StrEnum):
    SINGLE_COLUMN = "single_column"
    SIDEBAR_LEFT = "sidebar_left"
    SIDEBAR_RIGHT = "sidebar_right"
    # A tinted band behind the name and contact line.
    HEADER_BAND = "header_band"

    @property
    def has_sidebar(self) -> bool:
        return self in (Layout.SIDEBAR_LEFT, Layout.SIDEBAR_RIGHT)


class Rule(StrEnum):
    """The line under the header."""

    NONE = "none"
    THIN = "thin"
    THICK = "thick"


class HeadingCase(StrEnum):
    UPPER = "upper"
    AS_WRITTEN = "as_written"


class BulletStyle(StrEnum):
    DOT = "dot"
    DASH = "dash"
    NONE = "none"


_HEX = re.compile(r"^#[0-9a-f]{6}$")


@dataclass(frozen=True, slots=True)
class TemplateSpec:
    layout: Layout = Layout.SINGLE_COLUMN
    heading_font: str = HEADING_FONT
    body_font: str = BODY_FONT
    accent_color: str = "#c67139"
    name_color: str = "#8a4a20"
    text_color: str = "#201e1d"
    rule_color: str = "#c67139"
    rule: Rule = Rule.THICK
    name_pt: float = NAME_PT
    heading_pt: float = HEADING_PT
    body_pt: float = BODY_PT
    # For a sidebar layout: which list sections sit in the sidebar.
    sidebar_kinds: tuple[SectionKind, ...] = field(default_factory=tuple)
    heading_case: HeadingCase = HeadingCase.UPPER
    bullet: BulletStyle = BulletStyle.DOT

    def get_rule_css(self) -> str:
        """The header's line as a CSS border."""
        widths = {Rule.NONE: "0", Rule.THIN: "1px", Rule.THICK: "3px"}
        return f"{widths[self.rule]} solid {self.rule_color}"

    def get_derived_pt(self) -> tuple[float, float, float]:
        """An entry's title, the contact line and small print, from the body
        size: the same steps the built-in looks always had."""
        return (self.body_pt + 1.0, self.body_pt - 0.5, self.body_pt - 1.0)

    def get_band_color(self) -> str:
        """The header band's tint: the accent, one part in eight, on white."""
        channels = (int(self.accent_color[i : i + 2], 16) for i in (1, 3, 5))
        return "#" + "".join(f"{round(255 - (255 - c) / 8):02x}" for c in channels)

    def is_in_sidebar(self, kind: SectionKind) -> bool:
        return self.layout.has_sidebar and kind in self.sidebar_kinds

    def to_dict(self) -> dict[str, Any]:
        return {
            "layout": str(self.layout),
            "heading_font": self.heading_font,
            "body_font": self.body_font,
            "accent_color": self.accent_color,
            "name_color": self.name_color,
            "text_color": self.text_color,
            "rule_color": self.rule_color,
            "rule": str(self.rule),
            "name_pt": self.name_pt,
            "heading_pt": self.heading_pt,
            "body_pt": self.body_pt,
            "sidebar_kinds": [str(k) for k in self.sidebar_kinds],
            "heading_case": str(self.heading_case),
            "bullet": str(self.bullet),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> TemplateSpec:
        """A spec from stored or sent values; anything malformed is a
        ``TemplateSpecError`` naming the value."""
        try:
            spec = cls(
                layout=Layout(data["layout"]),
                heading_font=str(data["heading_font"]),
                body_font=str(data["body_font"]),
                accent_color=str(data["accent_color"]).lower(),
                name_color=str(data["name_color"]).lower(),
                text_color=str(data["text_color"]).lower(),
                rule_color=str(data["rule_color"]).lower(),
                rule=Rule(data["rule"]),
                name_pt=float(data["name_pt"]),
                heading_pt=float(data["heading_pt"]),
                body_pt=float(data["body_pt"]),
                sidebar_kinds=tuple(SectionKind(k) for k in data.get("sidebar_kinds", [])),
                heading_case=HeadingCase(data["heading_case"]),
                bullet=BulletStyle(data["bullet"]),
            )
        except (KeyError, ValueError, TypeError) as exc:
            raise TemplateSpecError(f"a template value could not be read: {exc}") from exc
        assert_spec_valid(spec)
        return spec


def get_contrast(foreground: str, background: str = "#ffffff") -> float:
    """The WCAG contrast ratio between two ``#rrggbb`` colours."""

    def luminance(color: str) -> float:
        channels = [int(color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
        linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    light, dark = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def assert_spec_valid(spec: TemplateSpec) -> None:
    """Every value in its set or range; the name and the text readable."""
    for name, font in (("heading font", spec.heading_font), ("body font", spec.body_font)):
        if font not in TEMPLATE_FONTS:
            raise TemplateSpecError(f"the {name} {font!r} is not one the résumé can set")
    for name, color in (
        ("accent colour", spec.accent_color),
        ("name colour", spec.name_color),
        ("text colour", spec.text_color),
        ("rule colour", spec.rule_color),
    ):
        if not _HEX.match(color):
            raise TemplateSpecError(f"the {name} {color!r} is not a #rrggbb colour")
    for name, color in (("name colour", spec.name_color), ("text colour", spec.text_color)):
        if get_contrast(color) < MIN_CONTRAST:
            raise TemplateSpecError(
                f"the {name} {color} is too light to read on a white page"
                f" (contrast under {MIN_CONTRAST}:1)"
            )
    for name, value, (low, high) in (
        ("name size", spec.name_pt, NAME_PT_RANGE),
        ("heading size", spec.heading_pt, HEADING_PT_RANGE),
        ("body size", spec.body_pt, BODY_PT_RANGE),
    ):
        if not low <= value <= high:
            raise TemplateSpecError(f"the {name} {value}pt is outside {low} to {high}pt")
    _assert_sidebar(spec.sidebar_kinds)


def _assert_sidebar(kinds: Iterable[SectionKind]) -> None:
    listed = list(kinds)
    if len(set(listed)) != len(listed):
        raise TemplateSpecError("a section is named twice for the sidebar")
    for kind in listed:
        if SHAPES[kind] is not SectionShape.LIST:
            raise TemplateSpecError(f"only lists can sit in the sidebar, not {kind}")


@dataclass(frozen=True, slots=True)
class BuiltInTemplate:
    template: Template
    name: str
    note: str
    spec: TemplateSpec


# The prototype's two templates: Organic and Plain.
BUILT_IN_TEMPLATES: dict[Template, BuiltInTemplate] = {
    Template.ORGANIC: BuiltInTemplate(
        template=Template.ORGANIC,
        name="Organic",
        note="Rounded, terracotta rule.",
        spec=TemplateSpec(),
    ),
    Template.PLAIN: BuiltInTemplate(
        template=Template.PLAIN,
        name="Plain",
        note="One page, evidence first.",
        spec=TemplateSpec(
            accent_color="#9b9691",
            name_color="#201e1d",
            rule_color="#cfcac5",
            rule=Rule.THIN,
        ),
    ),
}


def get_built_in_spec(template: Template) -> TemplateSpec:
    return BUILT_IN_TEMPLATES[template].spec
