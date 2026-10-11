"""Every font a résumé may name is one the PDF can set (ADR 0038, ADR 0047).

The worker image carries the fonts; fontconfig must find each by the very
name the domain lists, or Pango quietly sets the fallback instead.
"""

from __future__ import annotations

import re
import subprocess
from typing import get_args

import pytest

from advisor.resume.domain.constants import FONTS_WITHOUT_BOLD, TEMPLATE_FONTS
from api.schemas.resume import FontName


def test_the_api_offers_exactly_the_fonts_the_domain_allows() -> None:
    assert set(get_args(FontName)) == set(TEMPLATE_FONTS)


@pytest.mark.parametrize("font", TEMPLATE_FONTS)
def test_the_image_has_each_font_under_its_own_name(font: str) -> None:
    listed = subprocess.run(  # noqa: S603 - a fixed program and a listed font name
        ["/usr/bin/fc-list", f":family={font}", "family", "weight"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout

    assert listed.strip(), f"fontconfig has no {font}"


def _weights(font: str) -> set[int]:
    """fontconfig's weights for a family: 80 regular, 200 bold, 205 extra bold."""
    listed = subprocess.run(  # noqa: S603 - a fixed program and a listed font name
        ["/usr/bin/fc-list", f":family={font}", "weight"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return {int(found) for found in re.findall(r"\d+", listed)}


@pytest.mark.parametrize("font", TEMPLATE_FONTS)
def test_a_font_is_listed_without_bold_only_when_it_has_no_bold_cut(font: str) -> None:
    """ADR 0075: the Bold switches are off for exactly these fonts."""
    has_bold = any(weight >= 200 for weight in _weights(font))
    assert has_bold == (font not in FONTS_WITHOUT_BOLD)
