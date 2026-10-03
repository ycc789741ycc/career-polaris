"""Starting a template from a file (ADR 0041): a PDF's style, read locally
into a draft ``TemplateSpec`` the user reviews before anything is saved.

The reader hands over ``StyleRun``s: each run of text's font, size, colour and
position, and never the text. ``get_template_spec_from_runs`` turns them into
a draft: the largest type is the name, the most common size the body, short
runs in capitals or a bold face the headings (else the sizes between body and
name); two columns of runs make a sidebar; the list markers' colour, or else a
colour that is not near grey, is the accent. Font names map to the bundled fonts by
kind. Whatever cannot be read takes Organic's value and is listed as
defaulted, so the editor can flag it.

A ``TemplateReading`` is the run the editor polls (ADR 0006). It keeps only
the draft and which values were read; no text, name or font name.
"""

from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from typing import Any

from advisor.resume.domain.constants import (
    BODY_PT_RANGE,
    HEADING_PT_RANGE,
    MIN_CONTRAST,
    NAME_PT_RANGE,
    SIDEBAR_MIN_GAP,
    SIDEBAR_MIN_SHARE,
)
from advisor.resume.domain.section import SectionKind
from advisor.resume.domain.template_spec import (
    BulletStyle,
    HeadingCase,
    Layout,
    TemplateSpec,
    assert_spec_valid,
    get_contrast,
)


class TemplateReadingError(ValueError):
    """A file with no style to read: no text on its first page."""

    code = "unreadable_file"


class FontKind(StrEnum):
    SERIF = "serif"
    SANS = "sans"
    DISPLAY = "display"
    MONO = "mono"


# The bundled font each kind is set in.
_FONT_FOR_KIND = {
    FontKind.SERIF: "DejaVu Serif",
    FontKind.SANS: "Figtree",
    FontKind.DISPLAY: "Caprasimo",
    FontKind.MONO: "DejaVu Sans Mono",
}

# Words in a font's name that say its kind, checked in this order: a
# "Mono" or "Code" face is monospaced whatever else it says.
_KIND_WORDS: tuple[tuple[FontKind, tuple[str, ...]], ...] = (
    (FontKind.MONO, ("mono", "courier", "code", "consol", "menlo", "typewriter")),
    (FontKind.DISPLAY, ("display", "poster", "caprasimo", "cooper", "abril", "lobster")),
    (FontKind.SANS, ("sans", "grotesk", "grotesque", "gothic")),
    (
        FontKind.SERIF,
        (
            "serif",
            "times",
            "garamond",
            "georgia",
            "roman",
            "baskerville",
            "cambria",
            "palatino",
            "bookman",
            "merriweather",
            "caslon",
            "didot",
            "bodoni",
            "minion",
            "charter",
            "playfair",
            "lora",
            "crimson",
        ),
    ),
)


def get_font_kind(font_name: str) -> FontKind | None:
    """The kind a font's name says it is, or None for a name with nothing to
    go on. Anything named that is not serif, display or mono reads as sans,
    the commonest résumé face."""
    name = font_name.split("+")[-1].lower().replace("-", " ").replace(",", " ")
    if not name.strip():
        return None
    for kind, words in _KIND_WORDS:
        if any(word in name for word in words):
            return kind
    return FontKind.SANS


@dataclass(frozen=True, slots=True)
class StyleRun:
    """One run of text on the page, as the reader saw it, without the text.
    Held in memory while a file is read; never stored."""

    font_name: str
    size_pt: float
    # The fill colour, as #rrggbb.
    color: str
    x: float
    y: float
    # How many characters it held, to weigh it: a count, not the text.
    length: int
    is_upper: bool = False
    # The list marker it starts with, if any.
    marker: BulletStyle | None = None


@dataclass(frozen=True, slots=True)
class TemplateDraft:
    spec: TemplateSpec
    # The spec's fields read from the file, and those that took Organic's.
    read: tuple[str, ...]
    defaulted: tuple[str, ...]


# A heading is a short run: at most this many characters.
_HEADING_MAX = 40

# The values a draft reports on, in the editor's order.
_FIELDS = (
    "layout",
    "heading_font",
    "body_font",
    "accent_color",
    "name_color",
    "text_color",
    "rule_color",
    "rule",
    "name_pt",
    "heading_pt",
    "body_pt",
    "sidebar_kinds",
    "heading_case",
    "bullet",
)


def get_template_spec_from_runs(runs: Sequence[StyleRun], *, page_width: float) -> TemplateDraft:
    """A draft spec from a page's runs. Raises ``TemplateReadingError`` when
    the page has no text. Every draft passes ``assert_spec_valid``."""
    runs = [r for r in runs if r.length > 0 and r.size_pt > 0]
    if not runs:
        raise TemplateReadingError("this file has no text to read a style from")
    read: dict[str, Any] = {}

    body_size = _most_common((round(r.size_pt * 2) / 2 for r in runs), weights=runs)
    name_run = max(runs, key=lambda r: (r.size_pt, r.length))
    body_runs = [r for r in runs if abs(r.size_pt - body_size) < 0.5]
    read["body_pt"] = _clamp(body_size, BODY_PT_RANGE)
    if name_run.size_pt >= body_size + 2:
        read["name_pt"] = _clamp(name_run.size_pt, NAME_PT_RANGE)
        if get_contrast(name_run.color) >= MIN_CONTRAST:
            read["name_color"] = name_run.color
        if (kind := get_font_kind(name_run.font_name)) is not None:
            read["heading_font"] = _FONT_FOR_KIND[kind]

    shorts = [
        r for r in runs if r is not name_run and r.length <= _HEADING_MAX and r.marker is None
    ]
    headings = [r for r in shorts if r.is_upper or _is_bold(r.font_name)] or [
        r for r in shorts if body_size + 0.25 < r.size_pt < name_run.size_pt - 0.25
    ]
    if headings:
        heading_size = _most_common((round(r.size_pt * 2) / 2 for r in headings), weights=None)
        read["heading_pt"] = _clamp(heading_size, HEADING_PT_RANGE)
        upper = sum(1 for r in headings if r.is_upper)
        read["heading_case"] = (
            HeadingCase.UPPER if upper * 2 >= len(headings) else HeadingCase.AS_WRITTEN
        )

    body_kinds = [k for r in body_runs if (k := get_font_kind(r.font_name)) is not None]
    if body_kinds:
        read["body_font"] = _FONT_FOR_KIND[Counter(body_kinds).most_common(1)[0][0]]
    text_color = _most_common((r.color for r in body_runs), weights=body_runs)
    if get_contrast(text_color) >= MIN_CONTRAST:
        read["text_color"] = text_color

    accents = [r for r in runs if r.marker is not None and _is_colourful(r.color)] or [
        r for r in runs if _is_colourful(r.color)
    ]
    if accents:
        accent = _most_common((r.color for r in accents), weights=None)
        read["accent_color"] = accent
        read["rule_color"] = accent

    markers = [r.marker for r in runs if r.marker is not None]
    if markers:
        read["bullet"] = Counter(markers).most_common(1)[0][0]

    layout = _get_layout(runs, page_width=page_width)
    read["layout"] = layout
    spec = replace(TemplateSpec(), **read)
    if layout.has_sidebar:
        # Which lists sat in it cannot be told without the text.
        spec = replace(spec, sidebar_kinds=(SectionKind.SKILLS,))
    assert_spec_valid(spec)
    return TemplateDraft(
        spec=spec,
        read=tuple(f for f in _FIELDS if f in read),
        defaulted=tuple(f for f in _FIELDS if f not in read),
    )


def _get_layout(runs: Sequence[StyleRun], *, page_width: float) -> Layout:
    """Two columns of runs, each starting at its own x across the page and
    each holding a fair share of the text, are a sidebar; the narrower share
    is the sidebar, and it is on its side of the page."""
    if page_width <= 0:
        return Layout.SINGLE_COLUMN
    starts = Counter(round(r.x / page_width, 2) for r in runs)
    total = sum(starts.values())
    columns = sorted(x for x, n in starts.items() if n / total >= SIDEBAR_MIN_SHARE)
    if len(columns) < 2 or columns[-1] - columns[0] < SIDEBAR_MIN_GAP:
        return Layout.SINGLE_COLUMN
    split = (columns[0] + columns[-1]) / 2
    left = sum(r.length for r in runs if r.x / page_width < split)
    right = sum(r.length for r in runs if r.x / page_width >= split)
    return Layout.SIDEBAR_LEFT if left < right else Layout.SIDEBAR_RIGHT


def _is_bold(font_name: str) -> bool:
    name = font_name.lower()
    return any(word in name for word in ("bold", "black", "heavy", "semibold"))


def _is_colourful(color: str) -> bool:
    """Not near black, white or grey: the channels spread apart."""
    channels = [int(color[i : i + 2], 16) for i in (1, 3, 5)]
    return max(channels) - min(channels) >= 48


def _clamp(value: float, bounds: tuple[float, float]) -> float:
    low, high = bounds
    return min(max(round(value * 2) / 2, low), high)


def _most_common[T](values: Iterable[T], *, weights: Sequence[StyleRun] | None) -> T:
    counts: Counter[T] = Counter()
    for index, value in enumerate(values):
        counts[value] += weights[index].length if weights is not None else 1
    return counts.most_common(1)[0][0]


class ReadingStatus(StrEnum):
    READING = "reading"
    READY = "ready"
    FAILED = "failed"


@dataclass(slots=True)
class TemplateReading:
    """One upload being read for its style. The file is in object storage
    only until it is read; the run keeps the draft and nothing of the file."""

    id: uuid.UUID
    owner_id: uuid.UUID
    status: ReadingStatus
    created_at: datetime
    storage_key: str | None = None
    spec: dict[str, Any] | None = None
    read: tuple[str, ...] = field(default_factory=tuple)
    defaulted: tuple[str, ...] = field(default_factory=tuple)
    error_code: str | None = None
    error_message: str | None = None
    finished_at: datetime | None = None

    @classmethod
    def create(cls, *, owner_id: uuid.UUID, storage_key: str, at: datetime) -> TemplateReading:
        return cls(
            id=uuid.uuid4(),
            owner_id=owner_id,
            status=ReadingStatus.READING,
            storage_key=storage_key,
            created_at=at,
        )

    def update_read(self, draft: TemplateDraft, *, at: datetime) -> None:
        self.status = ReadingStatus.READY
        self.spec = draft.spec.to_dict()
        self.read = draft.read
        self.defaulted = draft.defaulted
        self.storage_key = None
        self.finished_at = at

    def update_failed(self, *, code: str, message: str, at: datetime) -> None:
        self.status = ReadingStatus.FAILED
        self.error_code = code
        self.error_message = message
        self.storage_key = None
        self.finished_at = at
