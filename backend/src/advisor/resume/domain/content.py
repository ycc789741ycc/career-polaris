"""The résumé as structured content, and the rules it must keep (section 2.9).

A résumé is sections and bullets, never free text. Every bullet the model
writes cites the Evidence it was written from — the grey note under each line
in the prototype — and a written bullet with nothing behind it is rejected:
that is the guard against invented claims. A line the user types themselves is
theirs to word, cited or not.

What each of the Target's requirements is covered by is decided here, from the
user's scores against the Target's bar, not by the model (section 2.9:
RequirementCoverage "is computed from the Target's TargetProfile and the user's
scores").
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any

from advisor.resume.domain.constants import PARTIAL_WITHIN
from advisor.resume.domain.section import (
    Bullet,
    Origin,
    ResumeError,
    Section,
    SectionKind,
    SectionSlot,
    assert_plan_valid,
    assert_section_well_formed,
)


class VersionSource(StrEnum):
    GENERATED = "generated"
    MANUAL = "manual"
    CHAT = "chat"
    # Rewritten after the user submitted answers in Fill the gap (ADR 0023).
    # Nothing writes it since ADR 0035; versions written before keep it.
    ANSWERS = "answers"


class Template(StrEnum):
    """Visual layout for export: rendering only, never a domain rule. The
    prototype's two: Organic (rounded, terracotta rule) and Plain."""

    ORGANIC = "organic"
    PLAIN = "plain"


class Verdict(StrEnum):
    COVERED = "covered"
    PARTIAL = "partial"
    GAP = "gap"


@dataclass(frozen=True, slots=True)
class Options:
    """How the Resume Advisor writes (the prototype's option toggles)."""

    # Quantify bullets with numbers from the evidence.
    metrics: bool = True
    # Order skills by what the Target screens for.
    reorder: bool = True
    # Fit on one page.
    trim: bool = False


@dataclass(frozen=True, slots=True)
class ResumeContent:
    """A header, and every section in its order, each shown or hidden
    (ADR 0039, ADR 0043)."""

    name: str
    headline: str
    contact: str
    sections: tuple[Section, ...]

    def bullets(self) -> Iterable[Bullet]:
        for section in self.sections:
            yield from section.get_bullets()

    def cited(self) -> set[str]:
        return {i for bullet in self.bullets() for i in bullet.evidence_ids}

    def get_section(self, slot: SectionSlot) -> Section | None:
        return next((s for s in self.sections if s.slot == slot), None)

    def get_plan(self) -> tuple[SectionSlot, ...]:
        """Which sections there are, in order, and which are shown: the
        résumé's plan."""
        return tuple(s.slot for s in self.sections)

    def get_shown(self) -> ResumeContent:
        """The résumé as it prints: its shown sections only."""
        return replace(self, sections=tuple(s for s in self.sections if s.is_shown))

    def with_citations(self, cite: Callable[[tuple[str, ...]], tuple[str, ...]]) -> ResumeContent:
        """The same résumé with every line's citations passed through ``cite``."""
        return replace(
            self,
            sections=tuple(
                s.update_bullets(lambda b: replace(b, evidence_ids=cite(b.evidence_ids)))
                for s in self.sections
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "headline": self.headline,
            "contact": self.contact,
            "sections": [s.to_dict() for s in self.sections],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ResumeContent:
        return cls(
            name=str(data.get("name", "")),
            headline=str(data.get("headline", "")),
            contact=str(data.get("contact", "")),
            sections=tuple(Section.from_dict(s) for s in data.get("sections", [])),
        )


def get_planned(content: ResumeContent, plan: Sequence[SectionSlot]) -> ResumeContent:
    """The content laid out as ``plan``: its sections in the plan's order,
    each shown or hidden as the plan says, an empty one for any the plan has
    and the content lacks, and none the plan does not have. Pure."""
    return replace(
        content,
        sections=tuple(
            replace(found, is_shown=slot.is_shown)
            if (found := content.get_section(slot)) is not None
            else Section.create_empty(slot)
            for slot in plan
        ),
    )


def assert_well_formed(content: ResumeContent) -> None:
    if not content.name.strip():
        raise ResumeError("a résumé needs a name")
    assert_plan_valid(content.get_plan())
    for section in content.sections:
        assert_section_well_formed(section)


def assert_written_lines_cited(content: ResumeContent) -> None:
    """Every line the model wrote cites the work it was written from, in
    whichever section it sits."""
    for section in content.sections:
        for bullet in section.get_bullets():
            if bullet.origin is Origin.WRITTEN and not bullet.evidence_ids:
                raise ResumeError(
                    f"a written line under {section.heading!r} cites no evidence: "
                    f"{bullet.text[:80]!r}"
                )


def mark_edits(previous: ResumeContent | None, edited: ResumeContent) -> ResumeContent:
    """A line the user changed is theirs; one left as it was keeps its origin.

    Matching is by exact text: a line that reads the same is the same line,
    wherever it moved, in whichever section.
    """
    before = {b.text: b for b in previous.bullets()} if previous else {}
    return replace(
        edited,
        sections=tuple(
            s.update_bullets(
                lambda b: before[b.text] if b.text in before else replace(b, origin=Origin.YOURS)
            )
            for s in edited.sections
        ),
    )


def settle_revision(
    current: ResumeContent,
    proposed: ResumeContent,
    resolve: Callable[[tuple[str, ...]], tuple[str, ...]],
) -> ResumeContent:
    """What a chat proposal really changes.

    A line whose text is unchanged is the line it was — origin and citations
    included — whatever the model says about it. Any other line is the model's
    writing, and must cite evidence like any written line; ``resolve`` turns
    what it cited into evidence ids.
    """
    before = {b.text: b for b in current.bullets()}
    return replace(
        proposed,
        sections=tuple(
            s.update_bullets(
                lambda b: (
                    before[b.text]
                    if b.text in before
                    else replace(b, origin=Origin.WRITTEN, evidence_ids=resolve(b.evidence_ids))
                )
            )
            for s in proposed.sections
        ),
    )


def get_headings_kept(content: ResumeContent, previous: ResumeContent | None) -> ResumeContent:
    """``content`` with each built-in section that has no heading of its own
    taking the one the user gave the same section in ``previous``: a rewrite
    by the model never undoes a renamed heading. Pure."""
    if previous is None:
        return content
    given = {s.slot: s.title for s in previous.sections if s.title}
    return replace(
        content,
        sections=tuple(
            replace(s, title=given[s.slot])
            if not s.title and s.kind is not SectionKind.CUSTOM and s.slot in given
            else s
            for s in content.sections
        ),
    )


def get_proposal_layout(
    current: ResumeContent,
    proposed: ResumeContent,
    asked: Sequence[bool | None],
) -> ResumeContent:
    """A chat proposal laid out over the résumé it revises (ADR 0043).

    ``asked`` is, per proposed section, whether the reply set it shown or
    hidden; ``None`` keeps the state the section has now, and a section the
    résumé did not have is shown. A built-in section the reply left out is
    kept as it is, after the rest: the chat removes a section of the user's
    own only. Pure."""
    states = {s.slot: s.is_shown for s in current.sections}
    laid_out = tuple(
        replace(section, is_shown=states.get(section.slot, True) if wanted is None else wanted)
        for section, wanted in zip(proposed.sections, asked, strict=True)
    )
    laid_out = get_headings_kept(replace(proposed, sections=laid_out), current).sections
    kept = {s.slot for s in laid_out}
    left_out = tuple(
        s for s in current.sections if s.kind is not SectionKind.CUSTOM and s.slot not in kept
    )
    return replace(proposed, sections=(*laid_out, *left_out))


@dataclass(frozen=True, slots=True)
class Coverage:
    requirement: str
    verdict: Verdict
    dimension_key: str | None
    evidence_ids: tuple[str, ...]
    # The evidence the user's answers to this requirement's gap became, in
    # Fill the gap (ADR 0044). What a gap may be claimed from.
    answer_ids: tuple[str, ...] = ()


def coverage(
    *,
    requirements: Sequence[str],
    requirement_map: Mapping[str, str | None],
    scores: Mapping[str, int],
    targets: Mapping[str, int],
    evidence: Mapping[str, Sequence[str]],
    answers: Mapping[str, Sequence[str]] | None = None,
) -> tuple[Coverage, ...]:
    """Covered, partial or gap for each requirement, with what backs it.

    A requirement mapped to one of the user's dimensions is judged by that
    dimension's score against the Target's bar for it. One mapped to nothing —
    or to a dimension the Target sets no bar for — has no evidence to judge by,
    and is a gap. ``answers`` lists, per requirement, the evidence the user's
    answers about it became; it changes no verdict.
    """
    answered = answers or {}
    result = []
    for requirement in requirements:
        key = requirement_map.get(requirement)
        answer_ids = tuple(answered.get(requirement, ()))
        if key is None or key not in scores or key not in targets:
            result.append(Coverage(requirement, Verdict.GAP, key, (), answer_ids))
            continue
        delta = scores[key] - targets[key]
        verdict = (
            Verdict.COVERED
            if delta >= 0
            else Verdict.PARTIAL
            if delta > -PARTIAL_WITHIN
            else Verdict.GAP
        )
        result.append(Coverage(requirement, verdict, key, tuple(evidence.get(key, ())), answer_ids))
    return tuple(result)


def get_claims_settled(
    content: ResumeContent,
    requirements: Iterable[str],
    gaps: Mapping[str, Iterable[str]],
) -> ResumeContent:
    """The content with a line's ``answers`` — the requirement it claims —
    cleared wherever nothing backs the claim (ADR 0046). Pure.

    A claim is dropped, the line kept, when it names no requirement of the
    Target, or names one marked gap that the line's citations do not rest on
    alone: ``gaps`` maps each gap to the evidence the user's answers about it
    became (ADR 0044), and a gap nobody answered about maps to none. The line
    still cites the user's own evidence, which is what guards against an
    invented fact; only the claim that it meets the requirement goes. A line
    the user wrote keeps its claim."""
    known = set(requirements)
    allowed = {requirement: frozenset(ids) for requirement, ids in gaps.items()}

    def is_backed(bullet: Bullet) -> bool:
        if bullet.answers is None:
            return True
        if bullet.answers not in known:
            return False
        if bullet.origin is not Origin.WRITTEN or bullet.answers not in allowed:
            return True
        answers = allowed[bullet.answers]
        return bool(answers) and bool(bullet.evidence_ids) and set(bullet.evidence_ids) <= answers

    return replace(
        content,
        sections=tuple(
            s.update_bullets(lambda b: b if is_backed(b) else replace(b, answers=None))
            for s in content.sections
        ),
    )
