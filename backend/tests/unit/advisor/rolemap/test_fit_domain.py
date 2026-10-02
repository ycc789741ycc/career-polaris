"""Fit arithmetic: one User x Role pair, its gaps and what it has no evidence
for (ADR 0028)."""

from __future__ import annotations

import pytest

from advisor.rolemap.domain import TargetScore, UncoveredRequirement, evaluate


def test_meeting_every_target_is_a_perfect_fit() -> None:
    result = evaluate(
        user_scores={"a": 80, "b": 70},
        targets=[TargetScore("a", 80), TargetScore("b", 70)],
        uncovered=[],
    )
    assert result.score == 100
    assert result.largest_gaps == ()


def test_exceeding_one_target_does_not_pay_for_missing_another() -> None:
    """A panel does not trade a strength off against a miss."""
    balanced = evaluate(
        user_scores={"a": 80, "b": 80},
        targets=[TargetScore("a", 80), TargetScore("b", 80)],
        uncovered=[],
    )
    lopsided = evaluate(
        user_scores={"a": 100, "b": 60},
        targets=[TargetScore("a", 80), TargetScore("b", 80)],
        uncovered=[],
    )
    assert balanced.score > lopsided.score


def test_a_gap_is_reported_with_its_size_and_direction() -> None:
    result = evaluate(user_scores={"lead": 49}, targets=[TargetScore("lead", 88)], uncovered=[])
    gap = result.gaps[0]
    assert gap.delta == -39 and gap.is_gap
    assert result.largest_gaps == (gap,)


def test_a_dimension_the_user_does_not_have_scores_as_zero_not_as_absent() -> None:
    result = evaluate(user_scores={}, targets=[TargetScore("unknown", 80)], uncovered=[])
    assert result.gaps[0].user_score == 0
    assert result.score == 0


def test_an_uncovered_requirement_lowers_fit_rather_than_being_a_footnote() -> None:
    """Someone with narrow evidence must not look like a strong fit."""
    covered = evaluate(user_scores={"a": 80}, targets=[TargetScore("a", 80)], uncovered=[])
    with_hole = evaluate(
        user_scores={"a": 80},
        targets=[TargetScore("a", 80)],
        uncovered=[UncoveredRequirement("Runs a multi-region platform", 1.0)],
    )
    assert covered.score == 100
    assert with_hole.score < covered.score
    assert with_hole.uncovered[0].statement == "Runs a multi-region platform"


def test_a_lightly_weighted_uncovered_requirement_costs_less_than_a_core_one() -> None:
    def fit(weight: float) -> int:
        return evaluate(
            user_scores={"a": 80},
            targets=[TargetScore("a", 80)],
            uncovered=[UncoveredRequirement("x", weight)],
        ).score

    assert fit(0.2) > fit(1.0)


def test_uncovered_requirements_alone_still_produce_a_score() -> None:
    result = evaluate(
        user_scores={},
        targets=[],
        uncovered=[UncoveredRequirement("x", 1.0)],
    )
    assert result.score == 0


def test_a_role_with_nothing_to_compare_is_not_a_fit_of_one_hundred() -> None:
    assert evaluate(user_scores={"a": 80}, targets=[], uncovered=[]).score == 0


def test_a_target_outside_the_scale_is_rejected() -> None:
    with pytest.raises(ValueError, match="between 0 and 100"):
        TargetScore("a", 120)
