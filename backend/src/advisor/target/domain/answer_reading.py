"""What the user's answers in Fill the gap say about a Target's gaps (ADR 0077).

A Target's fit is arithmetic over the scores of the user's latest analysis, so
answering moved nothing until the next analysis. Now one AI call reads each
answered gap against the answers given about it: a dimension gap gets the
score the answers support, an uncovered requirement whether they cover it.
The fit is then worked out again here, locally, with the fit's own
arithmetic: closing part of a gap is worth that part of its lift.

The readings belong to the Target, not to the role map: 03 Roles never reads
from the Advisor, so its fit moves only on a rebuild after a new analysis. A
new analysis reads the answers as evidence itself, so a reading counts only
while the analysis it was taken against is the latest.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum

from advisor.target.domain.snapshot import DimensionGap, TargetSnapshot, UncoveredGap


class Coverage(StrEnum):
    """How far the answers cover a requirement nothing else spoke to."""

    COVERED = "covered"
    PARTLY = "partly"
    NOT = "not"


@dataclass(frozen=True, slots=True)
class AnswerReading:
    """One gap of one Target, as the answers given about it read: a score for
    a dimension gap, or a coverage for an uncovered requirement. Cites the
    answers it rests on, and nothing else."""

    id: uuid.UUID
    owner_id: uuid.UUID
    role_id: uuid.UUID | None
    job_posting_id: uuid.UUID | None
    private_job_posting_id: uuid.UUID | None
    question_set_id: uuid.UUID
    # The analysis whose scores the fit was taken against.
    assessment_id: uuid.UUID
    gap_key: str
    # A dimension gap's score with the answers taken into account, 0-100.
    score: int | None
    # An uncovered requirement's coverage by the answers.
    coverage: Coverage | None
    reasoning: str
    evidence_ids: tuple[str, ...]
    model_id: str
    template_version: str
    created_at: datetime


def get_newest_readings(readings: Iterable[AnswerReading]) -> dict[str, AnswerReading]:
    """The newest reading of each gap: a later submit reads a gap again.
    Pure."""
    newest: dict[str, AnswerReading] = {}
    for reading in sorted(readings, key=lambda r: r.created_at):
        newest[reading.gap_key] = reading
    return newest


def get_answered_snapshot(
    snapshot: TargetSnapshot, readings: Iterable[AnswerReading]
) -> TargetSnapshot:
    """The snapshot with what the answers say laid over it. Pure.

    A dimension gap takes its reading's score; the fit gains the share of the
    gap's lift that closes, or loses it when the answers show less than the
    analysis assumed (a dimension already clear of its bar is left alone, as
    its weight is not known here). A covered requirement leaves the uncovered
    list and the fit gains its lift; a partly covered one stays at half its
    weight and half its lift, gaining the other half. The fit stays 0-100.
    ``answered_from`` keeps the fit before.
    """
    newest = get_newest_readings(readings)
    if not newest or snapshot.fit_score is None:
        return snapshot
    gained = 0.0
    dimensions: list[DimensionGap] = []
    for gap in snapshot.dimensions:
        reading = newest.get(gap.key)
        shortfall = gap.target_score - gap.user_score
        if reading is None or reading.score is None or shortfall <= 0:
            dimensions.append(gap)
            continue
        closed = min(reading.score, gap.target_score) - gap.user_score
        per_point = gap.lift / shortfall
        gained += per_point * closed
        dimensions.append(
            replace(
                gap,
                user_score=reading.score,
                lift=round(per_point * max(0, gap.target_score - reading.score)),
            )
        )
    uncovered: list[UncoveredGap] = []
    for requirement in snapshot.uncovered:
        reading = newest.get(requirement.key)
        coverage = reading.coverage if reading is not None else None
        if coverage is Coverage.COVERED:
            gained += requirement.lift
        elif coverage is Coverage.PARTLY:
            half = requirement.lift / 2
            gained += half
            uncovered.append(replace(requirement, weight=requirement.weight / 2, lift=round(half)))
        else:
            uncovered.append(requirement)
    if not gained and dimensions == list(snapshot.dimensions):
        return snapshot
    return replace(
        snapshot,
        fit_score=max(0, min(100, round(snapshot.fit_score + gained))),
        dimensions=tuple(dimensions),
        uncovered=tuple(uncovered),
        answered_from=snapshot.fit_score,
    )
