"""The career timeline half of a CareerProfile.

The timeline is the analysis's reading of the evidence: each position a
résumé line or an answer states, cited to it, replaced by every successful
analysis (ADR 0045). It is a reading, not evidence, and moves no profile
version.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime


class TimelineError(ValueError):
    """A position read from the evidence that breaks the rules: rejected, not
    repaired."""


@dataclass(frozen=True, slots=True)
class Position:
    title: str
    company: str
    started_on: date
    ended_on: date | None

    @property
    def is_current(self) -> bool:
        return self.ended_on is None

    def months(self, *, as_of: date) -> int:
        end = self.ended_on or as_of
        return max(0, (end.year - self.started_on.year) * 12 + end.month - self.started_on.month)


def total_experience_months(positions: list[Position], *, as_of: date) -> int:
    """Overlapping positions are counted once.

    Someone who contracted for two companies at the same time has not worked
    twice as long, and a resume that claims so does not survive an interview.
    """
    if not positions:
        return 0

    spans = sorted(
        (p.started_on, p.ended_on or as_of)
        for p in positions
        if (p.ended_on or as_of) >= p.started_on
    )
    merged: list[tuple[date, date]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))

    return sum((end.year - start.year) * 12 + end.month - start.month for start, end in merged)


@dataclass(frozen=True, slots=True)
class PositionReading:
    """A position as the analysis read it, with what it cites."""

    title: str
    company: str
    started_on: date
    ended_on: date | None
    evidence_ids: tuple[str, ...]


def assert_position_readings_valid(
    readings: Iterable[PositionReading], *, citable: set[str], as_of: date
) -> None:
    """Every position names a title and a company, starts no later than it
    ends and neither lies in the future, and cites at least one fact that can
    state a position — a résumé line or an answer — and nothing else.
    ``citable`` holds those facts' ids."""
    for reading in readings:
        where = f"{reading.title!r} at {reading.company!r}"
        if not reading.title.strip() or not reading.company.strip():
            raise TimelineError("a position needs a title and a company")
        latest = reading.ended_on or reading.started_on
        if reading.started_on > as_of or latest > as_of:
            raise TimelineError(f"{where} is dated in the future")
        if reading.ended_on is not None and reading.ended_on < reading.started_on:
            raise TimelineError(f"{where} ends before it starts")
        if not reading.evidence_ids:
            raise TimelineError(f"{where} cites nothing")
        if not set(reading.evidence_ids) <= citable:
            raise TimelineError(f"{where} cites something that does not state a position")


@dataclass(slots=True)
class CareerPosition:
    """One position on the career timeline."""

    id: uuid.UUID
    owner_id: uuid.UUID
    title: str
    company: str
    started_on: date
    ended_on: date | None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    # The résumé lines and answers it was read from, and the analysis that
    # read it (ADR 0045); empty and None on rows written before.
    evidence_ids: tuple[str, ...] = ()
    skill_assessment_id: uuid.UUID | None = None

    @property
    def value(self) -> Position:
        return Position(
            title=self.title,
            company=self.company,
            started_on=self.started_on,
            ended_on=self.ended_on,
        )
