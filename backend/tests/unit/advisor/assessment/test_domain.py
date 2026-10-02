"""Dimension bounds, lineage, and profile confidence."""

from __future__ import annotations

import pytest

from advisor.assessment.domain import (
    DimensionCountError,
    DimensionScore,
    LineageKind,
    assert_ids_unique,
    assert_within_bounds,
    derive_lineage,
    dropped_ids,
    profile_confidence,
    thin_evidence,
)


def dim(id_: str, name: str = "Name", score: int = 70, confidence: float = 0.8) -> DimensionScore:
    return DimensionScore(
        dimension_id=id_,
        name=name,
        short_name=name[:10],
        score=score,
        confidence=confidence,
        read="A read.",
        evidence_ids=("e1",),
    )


def dims(count: int) -> list[DimensionScore]:
    return [dim(f"d{i}") for i in range(count)]


# -- bounds -----------------------------------------------------------------


@pytest.mark.parametrize("count", [5, 7, 10])
def test_a_count_within_bounds_is_accepted(count: int) -> None:
    assert_within_bounds(dims(count))


def test_too_few_dimensions_asks_for_more_sources_rather_than_invention() -> None:
    with pytest.raises(DimensionCountError, match="connect more sources"):
        assert_within_bounds(dims(4))


def test_too_many_dimensions_asks_for_a_merge() -> None:
    with pytest.raises(DimensionCountError, match="merge related dimensions"):
        assert_within_bounds(dims(11))


def test_duplicate_dimension_ids_are_rejected() -> None:
    with pytest.raises(ValueError, match=r"repeated: \['d1'\]"):
        assert_ids_unique([dim("d1"), dim("d2"), dim("d1")])


def test_a_score_outside_the_scale_is_rejected() -> None:
    with pytest.raises(ValueError, match="between 0 and 100"):
        dim("d1", score=140)


# -- lineage ----------------------------------------------------------------


def test_reusing_an_id_with_the_same_name_is_not_a_change() -> None:
    previous = {"rel": "Testing & Reliability"}
    assert derive_lineage(previous, [dim("rel", "Testing & Reliability")]) == []


def test_a_reused_id_with_a_new_name_is_a_rename_not_a_new_dimension() -> None:
    """Radar history must still line up after a rename."""
    previous = {"rel": "Testing & Reliability"}
    entries = derive_lineage(previous, [dim("rel", "Reliability Engineering")])
    assert len(entries) == 1
    assert entries[0].kind is LineageKind.RENAMED
    assert entries[0].previous_name == "Testing & Reliability"


def test_a_genuinely_new_id_is_recorded_as_added() -> None:
    entries = derive_lineage({"rel": "Reliability"}, [dim("rel", "Reliability"), dim("prod")])
    assert [e.kind for e in entries] == [LineageKind.ADDED]
    assert entries[0].dimension_id == "prod"


def test_an_id_that_disappears_is_reported_so_history_is_not_orphaned() -> None:
    assert dropped_ids({"rel": "Reliability", "old": "Old"}, [dim("rel", "Reliability")]) == {"old"}


# -- follow-up trigger ------------------------------------------------------


def test_low_confidence_dimensions_trigger_follow_up_questions() -> None:
    dimensions = [dim("a", confidence=0.9), dim("b", confidence=0.3), dim("c", confidence=0.55)]
    assert [d.dimension_id for d in thin_evidence(dimensions, threshold=0.6)] == ["b", "c"]


def test_a_confident_assessment_asks_nothing() -> None:
    assert thin_evidence([dim("a", confidence=0.9)], threshold=0.6) == []


def test_confidence_exactly_at_the_threshold_is_confident_enough() -> None:
    assert thin_evidence([dim("a", confidence=0.6)], threshold=0.6) == []


# -- profile confidence (domain decision 28) ----------------------------------


def test_profile_confidence_is_the_mean_of_the_dimensions_confidence() -> None:
    assert profile_confidence([dim("a", confidence=0.9), dim("b", confidence=0.6)]) == (
        pytest.approx(0.75)
    )


def test_an_assessment_with_no_dimensions_has_no_profile_confidence() -> None:
    assert profile_confidence([]) is None
