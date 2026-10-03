"""Résumé content for tests: the three sections every résumé starts with."""

from __future__ import annotations

from advisor.resume.domain import Bullet, Entry, ResumeContent, Section, SectionKind


def make_content(
    *bullets: Bullet,
    name: str = "Maya Lin Chen",
    summary: str = "Builds payment systems.",
    skills: tuple[str, ...] = ("Go", "Postgres"),
    title: str = "Backend Engineer",
    org: str = "Kestrel",
    when: str = "2022 — now",
) -> ResumeContent:
    return ResumeContent(
        name=name,
        headline="Backend Engineer",
        contact="maya@example.com",
        sections=(
            Section(SectionKind.SUMMARY, text=summary),
            Section(SectionKind.EXPERIENCE, entries=(Entry(title, org, when, "", bullets),)),
            Section(SectionKind.SKILLS, items=skills),
        ),
    )


def get_lines(content: ResumeContent) -> tuple[Bullet, ...]:
    """The lines of the first experience entry."""
    experience = next(s for s in content.sections if s.kind is SectionKind.EXPERIENCE)
    return experience.entries[0].bullets
