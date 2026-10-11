"""A Target's fit with the answers given in Fill the gap read into it (ADR
0077): worked out locally, by the fit's own arithmetic."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from advisor.target.domain import (
    AnswerReading,
    Coverage,
    DimensionGap,
    Requirement,
    RequirementBasis,
    TargetRef,
    TargetSnapshot,
    UncoveredGap,
    get_answered_snapshot,
)

REF = TargetRef("00000000-0000-0000-0000-0000000000aa")
SET = uuid.UUID("00000000-0000-0000-0000-0000000000cc")


def _snapshot() -> TargetSnapshot:
    return TargetSnapshot(
        ref=REF,
        title="Staff Backend Engineer",
        company="Northwind Pay",
        role_id=REF.role_id,
        role_name="Staff Backend Engineer",
        requirements=(Requirement("Own incidents", 1.0, "advanced"),),
        basis=RequirementBasis.ROLE,
        fit_score=60,
        dimensions=(
            DimensionGap("incidents", "Incident response", 50, 80, lift=12),
            DimensionGap("go", "Go", 90, 70, lift=0),
        ),
        uncovered=(
            UncoveredGap("Multi-region capacity", 0.5, lift=8),
            UncoveredGap("Kubernetes in production", 0.5, lift=6),
        ),
        requirement_map={"Own incidents": "incidents"},
        taken_at=datetime(2026, 10, 12, tzinfo=UTC),
    )


def _reading(
    key: str,
    *,
    score: int | None = None,
    coverage: Coverage | None = None,
    at: int = 1,
) -> AnswerReading:
    return AnswerReading(
        id=uuid.uuid4(),
        owner_id=uuid.uuid4(),
        role_id=uuid.UUID(REF.role_id or ""),
        job_posting_id=None,
        private_job_posting_id=None,
        question_set_id=SET,
        assessment_id=uuid.uuid4(),
        gap_key=key,
        score=score,
        coverage=coverage,
        reasoning="",
        evidence_ids=("a1",),
        model_id="claude-opus-5",
        template_version="answer_reading@v1",
        created_at=datetime(2026, 10, 12, at, tzinfo=UTC),
    )


def test_closing_part_of_a_dimension_gap_gains_that_part_of_its_lift() -> None:
    answered = get_answered_snapshot(_snapshot(), [_reading("dim:incidents", score=70)])

    incidents = answered.dimensions[0]
    # 20 of the 30 points short closed: two thirds of 12.
    assert (answered.fit_score, answered.answered_from) == (68, 60)
    assert (incidents.user_score, incidents.lift) == (70, 4)


def test_a_score_past_the_bar_earns_only_the_gap() -> None:
    answered = get_answered_snapshot(_snapshot(), [_reading("dim:incidents", score=95)])

    assert answered.fit_score == 72
    assert answered.dimensions[0].lift == 0
    assert [d.key for d in answered.dimensions if d.delta < 0] == []


def test_an_answer_showing_less_than_the_analysis_assumed_lowers_the_fit() -> None:
    answered = get_answered_snapshot(_snapshot(), [_reading("dim:incidents", score=35)])

    assert answered.fit_score == 54
    assert answered.dimensions[0].lift == 18


def test_a_covered_requirement_leaves_the_gaps_and_a_partly_covered_one_halves() -> None:
    answered = get_answered_snapshot(
        _snapshot(),
        [
            _reading("req:multi-region-capacity", coverage=Coverage.COVERED),
            _reading("req:kubernetes-in-production", coverage=Coverage.PARTLY),
        ],
    )

    assert answered.fit_score == 71
    assert [(u.statement, u.weight, u.lift) for u in answered.uncovered] == [
        ("Kubernetes in production", 0.25, 3)
    ]


def test_not_covered_and_a_cleared_dimension_change_nothing() -> None:
    snapshot = _snapshot()
    answered = get_answered_snapshot(
        snapshot,
        [
            _reading("req:multi-region-capacity", coverage=Coverage.NOT),
            _reading("dim:go", score=40),
        ],
    )

    assert answered == snapshot


def test_the_newest_reading_of_a_gap_counts() -> None:
    answered = get_answered_snapshot(
        _snapshot(),
        [_reading("dim:incidents", score=80, at=2), _reading("dim:incidents", score=60, at=1)],
    )

    assert answered.fit_score == 72


def test_the_fit_before_the_answers_round_trips_with_the_snapshot() -> None:
    answered = get_answered_snapshot(_snapshot(), [_reading("dim:incidents", score=70)])

    assert TargetSnapshot.from_dict(answered.to_dict()) == answered
    assert TargetSnapshot.from_dict(_snapshot().to_dict()).answered_from is None
