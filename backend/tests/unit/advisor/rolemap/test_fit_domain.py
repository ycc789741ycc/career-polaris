"""Fit arithmetic: one User x Role pair, its gaps and what it has no evidence
for (ADR 0028)."""

from __future__ import annotations

import pytest

from advisor.rolemap.domain import (
    TargetScore,
    UncoveredRequirement,
    evaluate,
    get_posting_fit,
    get_requirements_digest,
)


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


# -- a posting's fit, worked out from an AI fit (Phase 8) ----------------------


def test_a_posting_fit_is_the_ai_fits_mapping_and_targets_evaluated() -> None:
    requirements = [
        {"statement": "Leads design", "weight": 0.9, "expected_level": "expert"},
        {"statement": "Kubernetes", "weight": 0.5, "expected_level": "advanced"},
    ]
    found = get_posting_fit(
        requirements=requirements,
        requirement_map={"Leads design": "leadership", "Kubernetes": None},
        target_profile={"leadership": 90},
        user_scores={"leadership": 70},
    )
    expected = evaluate(
        user_scores={"leadership": 70},
        targets=[TargetScore("leadership", 90)],
        uncovered=[UncoveredRequirement("Kubernetes", 0.5)],
    )
    assert found == expected


def test_a_posting_fit_drops_what_the_user_does_not_have() -> None:
    """A target, or a mapping, on a dimension the user lacks is the model
    drifting: the target goes, and the requirement is uncovered."""
    found = get_posting_fit(
        requirements=[{"statement": "Leads design", "weight": 0.9, "expected_level": "expert"}],
        requirement_map={"Leads design": "invented"},
        target_profile={"invented": 90, "leadership": 60},
        user_scores={"leadership": 70},
    )
    assert [g.dimension_id for g in found.gaps] == ["leadership"]
    assert [u.statement for u in found.uncovered] == ["Leads design"]


def test_a_requirement_listed_twice_counts_once() -> None:
    twice = {"statement": "Kubernetes", "weight": 0.5, "expected_level": "advanced"}
    found = get_posting_fit(
        requirements=[twice, twice],
        requirement_map={},
        target_profile={},
        user_scores={"leadership": 70},
    )
    assert len(found.uncovered) == 1


# -- what a fit read (Phase 8) -------------------------------------------------

_READ = [
    {"statement": "Leads design", "weight": 0.9, "expected_level": "expert"},
    {"statement": "Kubernetes", "weight": 0.5, "expected_level": "advanced"},
]


def test_the_same_requirements_and_prompt_read_the_same() -> None:
    copied = [dict(r) for r in _READ]
    assert get_requirements_digest(_READ, template_version="fit@v1") == get_requirements_digest(
        copied, template_version="fit@v1"
    )


@pytest.mark.parametrize(
    "changed",
    [
        [{**_READ[0], "weight": 0.8}, _READ[1]],
        [{**_READ[0], "expected_level": "senior"}, _READ[1]],
        [_READ[0]],
        [_READ[1], _READ[0]],
    ],
)
def test_any_change_to_what_is_read_changes_the_digest(changed: list[dict[str, object]]) -> None:
    assert get_requirements_digest(changed, template_version="fit@v1") != get_requirements_digest(
        _READ, template_version="fit@v1"
    )


def test_a_new_fit_prompt_changes_every_digest() -> None:
    assert get_requirements_digest(_READ, template_version="fit@v2") != get_requirements_digest(
        _READ, template_version="fit@v1"
    )
