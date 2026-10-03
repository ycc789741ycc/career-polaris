"""Reading a PDF's style, never its words (ADR 0041).

Walks the first page with pypdf, opened through ``kernel.documents``'s guards,
and records each run of text's font name, size, fill colour and position as a
``StyleRun``. The text itself is looked at only to count it, to tell whether
it is in capitals and which list marker it starts with; it is never kept,
returned or logged. Runs on the worker only, like every upload: the file is a
stranger's.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

from advisor.resume.domain import BulletStyle, StyleRun
from kernel.documents import open_pdf

_DOT_MARKERS = frozenset("•●▪◦·■")
# An en dash, an em dash or a hyphen.
_DASH_MARKERS = frozenset("\u2013\u2014-")


def read_style_runs(content: bytes, *, max_pages: int) -> tuple[list[StyleRun], float]:
    """The first page's runs, and its width in points. Raises
    ``ValidationError`` for a file ``kernel.documents`` will not open."""
    page = open_pdf(content, max_pages=max_pages).pages[0]
    width = float(page.mediabox.width)
    runs: list[StyleRun] = []
    fill = "#000000"
    saved: list[str] = []

    def before(operator: bytes, operands: Sequence[Any], cm: Any, tm: Any) -> None:
        nonlocal fill
        if operator == b"q":
            saved.append(fill)
        elif operator == b"Q":
            fill = saved.pop() if saved else fill
        elif operator in (b"rg", b"g", b"k", b"sc", b"scn"):
            fill = _get_fill(operands) or fill

    def text(chunk: str, cm: Any, tm: Any, font: Any, font_size: Any) -> None:
        stripped = chunk.strip()
        if not stripped or not font_size:
            return
        matrix = _multiply(tm, cm)
        letters = [c for c in stripped if c.isalpha()]
        runs.append(
            StyleRun(
                font_name=str(font.get("/BaseFont", "")) if font else "",
                size_pt=float(font_size) * math.hypot(matrix[2], matrix[3]),
                color=fill,
                x=matrix[4],
                y=matrix[5],
                length=len(stripped),
                is_upper=len(letters) > 1 and all(c.isupper() for c in letters),
                marker=_get_marker(stripped),
            )
        )

    page.extract_text(visitor_operand_before=before, visitor_text=text)
    return runs, width


def _get_fill(operands: Sequence[Any]) -> str | None:
    """A fill colour from its operands: grey, RGB or CMYK. A pattern or a
    named colour space gives none."""
    try:
        values = [float(v) for v in operands]
    except (TypeError, ValueError):
        return None
    if len(values) == 1:
        rgb = values * 3
    elif len(values) == 3:
        rgb = values
    elif len(values) == 4:
        c, m, y, k = values
        rgb = [(1 - c) * (1 - k), (1 - m) * (1 - k), (1 - y) * (1 - k)]
    else:
        return None
    return "#" + "".join(f"{round(min(max(v, 0.0), 1.0) * 255):02x}" for v in rgb)


def _get_marker(text: str) -> BulletStyle | None:
    first = text[0]
    if first in _DOT_MARKERS:
        return BulletStyle.DOT
    if first in _DASH_MARKERS and (len(text) == 1 or text[1] == " "):
        return BulletStyle.DASH
    return None


def _multiply(a: Sequence[float], b: Sequence[float]) -> list[float]:
    """Two PDF matrices, ``[a b c d e f]``, multiplied: ``a`` then ``b``."""
    a0, a1, a2, a3, a4, a5 = (float(v) for v in a)
    b0, b1, b2, b3, b4, b5 = (float(v) for v in b)
    return [
        a0 * b0 + a1 * b2,
        a0 * b1 + a1 * b3,
        a2 * b0 + a3 * b2,
        a2 * b1 + a3 * b3,
        a4 * b0 + a5 * b2 + b4,
        a4 * b1 + a5 * b3 + b5,
    ]
