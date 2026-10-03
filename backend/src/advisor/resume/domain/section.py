"""A résumé's sections: which there are, in what order, and what each holds
(ADR 0039).

A résumé is a header and an ordered list of sections the user chooses.
Experience is always among them; every other kind appears at most once, and a
few custom sections carry the user's own heading. Each kind has one shape:

* text — the summary;
* entries — experience, side projects, open source, education, talks and
  writing: each entry a title, an organisation, when, an optional link and
  bullets;
* list — skills, certifications: short items;
* bullets — a custom section: lines under the user's heading.

Every bullet keeps its citations, its origin and the requirement it answers,
wherever it sits, so a line the model wrote cites its evidence in any section.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any

from advisor.resume.domain.constants import (
    MAX_BULLETS_PER_ROLE,
    MAX_CUSTOM_SECTIONS,
    MAX_ITEM,
    MAX_LINK,
    MAX_ROLES,
    MAX_SECTION_TITLE,
    MAX_SECTIONS,
    MAX_SKILLS,
    MAX_SUMMARY,
    MAX_TEXT,
)


class ResumeError(ValueError):
    """Content that breaks the rules; it is rejected, not repaired."""


class Origin(StrEnum):
    """Who wrote a line. Only the model's lines must cite evidence."""

    WRITTEN = "written"
    YOURS = "yours"


class SectionKind(StrEnum):
    SUMMARY = "summary"
    EXPERIENCE = "experience"
    SIDE_PROJECTS = "side_projects"
    OPEN_SOURCE = "open_source"
    EDUCATION = "education"
    TALKS_AND_WRITING = "talks_and_writing"
    SKILLS = "skills"
    CERTIFICATIONS = "certifications"
    CUSTOM = "custom"


class SectionShape(StrEnum):
    TEXT = "text"
    ENTRIES = "entries"
    LIST = "list"
    BULLETS = "bullets"


SHAPES: dict[SectionKind, SectionShape] = {
    SectionKind.SUMMARY: SectionShape.TEXT,
    SectionKind.EXPERIENCE: SectionShape.ENTRIES,
    SectionKind.SIDE_PROJECTS: SectionShape.ENTRIES,
    SectionKind.OPEN_SOURCE: SectionShape.ENTRIES,
    SectionKind.EDUCATION: SectionShape.ENTRIES,
    SectionKind.TALKS_AND_WRITING: SectionShape.ENTRIES,
    SectionKind.SKILLS: SectionShape.LIST,
    SectionKind.CERTIFICATIONS: SectionShape.LIST,
    SectionKind.CUSTOM: SectionShape.BULLETS,
}

# The heading each kind is printed under; a custom section prints its own.
HEADINGS: dict[SectionKind, str] = {
    SectionKind.SUMMARY: "Summary",
    SectionKind.EXPERIENCE: "Experience",
    SectionKind.SIDE_PROJECTS: "Side projects",
    SectionKind.OPEN_SOURCE: "Open source",
    SectionKind.EDUCATION: "Education",
    SectionKind.TALKS_AND_WRITING: "Talks & writing",
    SectionKind.SKILLS: "Skills",
    SectionKind.CERTIFICATIONS: "Certifications",
    SectionKind.CUSTOM: "",
}


@dataclass(frozen=True, slots=True)
class Bullet:
    text: str
    evidence_ids: tuple[str, ...] = ()
    origin: Origin = Origin.WRITTEN
    # Which of the Target's requirements this line answers, if any.
    answers: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "evidence_ids": list(self.evidence_ids),
            "origin": str(self.origin),
            "answers": self.answers,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Bullet:
        return cls(
            text=str(data.get("text", "")),
            evidence_ids=tuple(str(i) for i in data.get("evidence_ids", [])),
            origin=Origin(data.get("origin", Origin.WRITTEN)),
            answers=data.get("answers"),
        )


@dataclass(frozen=True, slots=True)
class Entry:
    """One position, project, school or talk: what it was, where, when."""

    title: str
    org: str = ""
    when: str = ""
    # Shown as text; never fetched, never made a live link.
    link: str = ""
    bullets: tuple[Bullet, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "org": self.org,
            "when": self.when,
            "link": self.link,
            "bullets": [b.to_dict() for b in self.bullets],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Entry:
        return cls(
            title=str(data.get("title", "")),
            org=str(data.get("org", "")),
            when=str(data.get("when", "")),
            link=str(data.get("link", "") or ""),
            bullets=tuple(Bullet.from_dict(b) for b in data.get("bullets", [])),
        )


@dataclass(frozen=True, slots=True)
class SectionSlot:
    """A section's place in a résumé's plan: its kind, and a custom one's
    heading."""

    kind: SectionKind
    title: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"kind": str(self.kind), "title": self.title}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> SectionSlot:
        kind = SectionKind(data["kind"])
        title = data.get("title")
        return cls(kind, str(title) if kind is SectionKind.CUSTOM and title else None)


@dataclass(frozen=True, slots=True)
class Section:
    """One section. Only the fields of its kind's shape are used."""

    kind: SectionKind
    # A custom section's heading; None for every other kind.
    title: str | None = None
    text: str = ""
    entries: tuple[Entry, ...] = ()
    items: tuple[str, ...] = ()
    bullets: tuple[Bullet, ...] = ()

    @property
    def shape(self) -> SectionShape:
        return SHAPES[self.kind]

    @property
    def heading(self) -> str:
        if self.kind is SectionKind.CUSTOM:
            return self.title or ""
        return HEADINGS[self.kind]

    @property
    def slot(self) -> SectionSlot:
        return SectionSlot(self.kind, self.title if self.kind is SectionKind.CUSTOM else None)

    @property
    def is_empty(self) -> bool:
        return not (self.text.strip() or self.entries or self.items or self.bullets)

    def get_bullets(self) -> Iterable[Bullet]:
        for entry in self.entries:
            yield from entry.bullets
        yield from self.bullets

    def update_bullets(self, change: Callable[[Bullet], Bullet]) -> Section:
        """The same section with every line passed through ``change``."""
        return replace(
            self,
            entries=tuple(
                replace(e, bullets=tuple(change(b) for b in e.bullets)) for e in self.entries
            ),
            bullets=tuple(change(b) for b in self.bullets),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": str(self.kind),
            "title": self.title,
            "text": self.text,
            "entries": [e.to_dict() for e in self.entries],
            "items": list(self.items),
            "bullets": [b.to_dict() for b in self.bullets],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Section:
        kind = SectionKind(data["kind"])
        title = data.get("title")
        return cls(
            kind=kind,
            title=str(title) if kind is SectionKind.CUSTOM and title is not None else None,
            text=str(data.get("text", "") or ""),
            entries=tuple(Entry.from_dict(e) for e in data.get("entries", []) or []),
            items=tuple(str(i) for i in data.get("items", []) or []),
            bullets=tuple(Bullet.from_dict(b) for b in data.get("bullets", []) or []),
        )

    @classmethod
    def create_empty(cls, slot: SectionSlot) -> Section:
        return cls(kind=slot.kind, title=slot.title)


# A new résumé's sections, as before sections could be chosen.
DEFAULT_PLAN: tuple[SectionSlot, ...] = (
    SectionSlot(SectionKind.SUMMARY),
    SectionSlot(SectionKind.EXPERIENCE),
    SectionSlot(SectionKind.SKILLS),
)


def assert_plan_valid(plan: Iterable[SectionSlot]) -> None:
    """Experience once, every other kind at most once, a few custom sections
    each with a heading, and not too many in all."""
    slots = list(plan)
    if len(slots) > MAX_SECTIONS:
        raise ResumeError(f"a résumé has at most {MAX_SECTIONS} sections")
    kinds = [s.kind for s in slots]
    if kinds.count(SectionKind.EXPERIENCE) != 1:
        raise ResumeError("a résumé always has its experience, once")
    for kind in SectionKind:
        if kind is not SectionKind.CUSTOM and kinds.count(kind) > 1:
            raise ResumeError(f"a résumé has one {HEADINGS[kind].lower()} section")
    custom = [s for s in slots if s.kind is SectionKind.CUSTOM]
    if len(custom) > MAX_CUSTOM_SECTIONS:
        raise ResumeError(f"at most {MAX_CUSTOM_SECTIONS} sections of your own")
    titles = [(s.title or "").strip() for s in custom]
    if any(not t for t in titles):
        raise ResumeError("a section of your own needs a heading")
    if any(len(t) > MAX_SECTION_TITLE for t in titles):
        raise ResumeError(f"a heading has at most {MAX_SECTION_TITLE} characters")
    if len({t.casefold() for t in titles}) != len(titles):
        raise ResumeError("two sections of your own have the same heading")


def assert_section_well_formed(section: Section) -> None:
    where = section.heading or "a section"
    if section.shape is SectionShape.TEXT and len(section.text) > MAX_SUMMARY:
        raise ResumeError(f"{where} is too long")
    if section.shape is SectionShape.ENTRIES:
        if len(section.entries) > MAX_ROLES:
            raise ResumeError(f"at most {MAX_ROLES} entries under {where}")
        for entry in section.entries:
            if not entry.title.strip():
                raise ResumeError(f"an entry under {where} has no title")
            if len(entry.link) > MAX_LINK:
                raise ResumeError(f"a link under {where} is too long")
            _assert_lines(entry.bullets, f"{entry.title!r}")
    if section.shape is SectionShape.LIST:
        if len(section.items) > MAX_SKILLS:
            raise ResumeError(f"at most {MAX_SKILLS} items under {where}")
        if any(not i.strip() or len(i) > MAX_ITEM for i in section.items):
            raise ResumeError(f"an item under {where} is empty or too long")
    if section.shape is SectionShape.BULLETS:
        _assert_lines(section.bullets, where)


def _assert_lines(bullets: tuple[Bullet, ...], where: str) -> None:
    if len(bullets) > MAX_BULLETS_PER_ROLE:
        raise ResumeError(f"at most {MAX_BULLETS_PER_ROLE} bullets under {where}")
    for bullet in bullets:
        if not bullet.text.strip():
            raise ResumeError(f"an empty line under {where}")
        if len(bullet.text) > MAX_TEXT:
            raise ResumeError(f"a line under {where} is too long")
