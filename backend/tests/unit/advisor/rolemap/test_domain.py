"""Hiring bar blending, role identity across rebuilds, and which recommended
candidates the market has."""

from __future__ import annotations

import itertools

import pytest

from advisor.rolemap.domain import (
    MIN_POSTINGS_FOR_A_ROLE,
    BarBasis,
    RoleChange,
    assign_postings,
    blend,
    choose_by_estimate,
    fit_estimates,
    keep_on_market,
    max_role_count,
    overlap,
    reconcile,
)

# -- hiring bar -------------------------------------------------------------


def test_with_no_reports_the_bar_is_an_estimate() -> None:
    bar = blend(estimated=62, estimate_confidence=0.4, reported=None, reporter_count=0)
    assert bar.value == 62
    assert bar.basis is BarBasis.ESTIMATED
    assert bar.is_estimate


def test_fewer_than_three_reporters_still_uses_the_estimate() -> None:
    """Below the minimum group size a figure could be traced to one person."""
    bar = blend(estimated=62, estimate_confidence=0.4, reported=90, reporter_count=2)
    assert bar.value == 62
    assert bar.basis is BarBasis.ESTIMATED


def test_three_reporters_start_to_move_the_bar() -> None:
    bar = blend(estimated=60, estimate_confidence=0.4, reported=90, reporter_count=3)
    assert 60 < bar.value < 90
    assert bar.basis is BarBasis.BLENDED


def test_more_reporters_pull_the_bar_further_toward_the_reports() -> None:
    few = blend(estimated=60, estimate_confidence=0.4, reported=90, reporter_count=3)
    many = blend(estimated=60, estimate_confidence=0.4, reported=90, reporter_count=9)
    assert many.value > few.value


def test_a_full_sample_is_reported_not_blended() -> None:
    bar = blend(estimated=60, estimate_confidence=0.4, reported=90, reporter_count=20)
    assert bar.value == 90
    assert bar.basis is BarBasis.REPORTED
    assert not bar.is_estimate


def test_the_bar_stays_on_the_scale() -> None:
    def bar(value: int) -> int:
        return blend(
            estimated=value, estimate_confidence=0.2, reported=None, reporter_count=0
        ).value

    assert bar(180) == 100
    assert bar(-40) == 0


# -- role identity ----------------------------------------------------------


def ids():
    counter = itertools.count(1)
    return lambda: f"new-{next(counter)}"


def test_identical_clusters_keep_their_role_ids() -> None:
    """A re-crawl that changes nothing must not renumber the user's roles."""
    previous = {"srbe": {"a", "b", "c"}, "staff": {"x", "y"}}
    result = reconcile(previous=previous, clusters=[{"a", "b", "c"}, {"x", "y"}], new_id=ids())
    assert result.assignments == {0: "srbe", 1: "staff"}
    assert result.lineage == ()


def test_a_cluster_that_gains_a_posting_is_still_the_same_role() -> None:
    previous = {"srbe": {"a", "b", "c"}}
    result = reconcile(previous=previous, clusters=[{"a", "b", "c", "d"}], new_id=ids())
    assert result.assignments == {0: "srbe"}


def test_a_genuinely_new_group_gets_a_new_id() -> None:
    previous = {"srbe": {"a", "b", "c"}}
    result = reconcile(previous=previous, clusters=[{"a", "b", "c"}, {"p", "q", "r"}], new_id=ids())
    assert result.assignments[0] == "srbe"
    assert result.assignments[1] == "new-1"
    assert [e.kind for e in result.lineage] == [RoleChange.ADDED]


def test_a_role_splitting_is_recorded_with_its_parent() -> None:
    """A goal pointing at the old role must be able to find its successor."""
    previous = {"srbe": {"a", "b", "c", "d"}}
    result = reconcile(previous=previous, clusters=[{"a", "b", "c"}, {"d"}], new_id=ids())
    split = [e for e in result.lineage if e.kind is RoleChange.SPLIT]
    assert len(split) == 1
    assert split[0].from_role_ids == ("srbe",)


def test_two_roles_collapsing_into_one_is_recorded_as_a_merge() -> None:
    previous = {"srbe": {"a", "b", "c"}, "fs": {"d"}}
    result = reconcile(previous=previous, clusters=[{"a", "b", "c", "d"}], new_id=ids())
    merged = [e for e in result.lineage if e.kind is RoleChange.MERGED]
    assert len(merged) == 1
    assert merged[0].role_id == "srbe"
    assert merged[0].from_role_ids == ("fs",)


def test_a_role_whose_postings_all_vanished_is_retired_not_silently_dropped() -> None:
    previous = {"srbe": {"a", "b"}, "gone": {"z"}}
    result = reconcile(previous=previous, clusters=[{"a", "b"}], new_id=ids())
    assert result.retired_role_ids == frozenset({"gone"})
    assert [e.role_id for e in result.lineage if e.kind is RoleChange.RETIRED] == ["gone"]


def test_a_barely_overlapping_cluster_is_not_the_same_role() -> None:
    previous = {"srbe": {"a", "b", "c", "d", "e"}}
    result = reconcile(previous=previous, clusters=[{"a", "z", "y", "x", "w"}], new_id=ids())
    assert result.assignments[0] == "new-1"


def test_the_first_clustering_gives_every_role_a_new_id() -> None:
    result = reconcile(previous={}, clusters=[{"a"}, {"b"}], new_id=ids())
    assert sorted(result.assignments.values()) == ["new-1", "new-2"]
    assert all(e.kind is RoleChange.ADDED for e in result.lineage)


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [
        ({"a"}, {"a"}, 1.0),
        ({"a"}, {"b"}, 0.0),
        ({"a", "b"}, {"b", "c"}, 1 / 3),
        (set(), set(), 0.0),
    ],
)
def test_overlap_is_jaccard(left: set[str], right: set[str], expected: float) -> None:
    assert overlap(left, right) == pytest.approx(expected)


# -- the cost ceiling -------------------------------------------------------


@pytest.mark.parametrize(
    ("postings", "expected"),
    [
        (0, 0),
        (MIN_POSTINGS_FOR_A_ROLE - 1, 0),
        (MIN_POSTINGS_FOR_A_ROLE, 1),
        (10, 3),
        (410, 10),
    ],
)
def test_no_more_roles_than_full_clusters_fit_or_than_a_build_keeps(
    postings: int, expected: int
) -> None:
    assert max_role_count(postings, ceiling=10) == expected


def test_the_ceiling_is_the_k_a_build_keeps() -> None:
    """k is a setting (ADR 0029): a smaller one lowers the ceiling."""
    assert max_role_count(410, ceiling=3) == 3
    assert max_role_count(4, ceiling=3) == 1


@pytest.mark.parametrize(("postings", "ceiling"), [(-1, 10), (10, -1)])
def test_a_negative_count_is_a_bug_not_zero_roles(postings: int, ceiling: int) -> None:
    with pytest.raises(ValueError, match="negative"):
        max_role_count(postings, ceiling=ceiling)


# -- matching candidates to the market (ADR 0024) ----------------------------


def _axis(index: int, weight: float = 1.0) -> list[float]:
    vector = [0.0] * 16
    vector[index] = weight
    return vector


def _near(index: int, lean: int, amount: float) -> list[float]:
    """Mostly along ``index``, tilted toward ``lean`` by ``amount``."""
    vector = _axis(index)
    vector[lean] = amount
    return vector


NO_TITLE_HITS: frozenset[int] = frozenset()


def test_a_posting_is_an_opening_for_the_candidate_it_is_nearest() -> None:
    candidates = [_axis(0), _axis(1)]
    postings = [_near(1, 0, 0.2), _near(0, 1, 0.2)]
    assert assign_postings(candidates, postings, [NO_TITLE_HITS] * 2) == [1, 0]


def test_a_posting_near_no_candidate_is_an_opening_for_none() -> None:
    assert assign_postings([_axis(0), _axis(1)], [_axis(5)], [NO_TITLE_HITS]) == [None]


def test_the_threshold_is_the_least_cosine_that_counts() -> None:
    # cos 45° is about 0.707
    posting = [_near(0, 1, 1.0)]
    assert assign_postings([_axis(0)], posting, [NO_TITLE_HITS], threshold=0.7) == [0]
    assert assign_postings([_axis(0)], posting, [NO_TITLE_HITS], threshold=0.75) == [None]


def test_a_posting_that_names_a_candidates_title_goes_to_it_even_when_another_is_nearer() -> None:
    candidates = [_axis(0), _axis(1)]
    posting = [_near(0, 1, 0.1)]
    assert assign_postings(candidates, posting, [frozenset({1})]) == [1]


def test_a_title_hit_counts_below_the_threshold() -> None:
    assert assign_postings([_axis(0)], [_axis(5)], [frozenset({0})]) == [0]


def test_of_several_title_hits_the_nearest_wins() -> None:
    candidates = [_axis(0), _axis(1), _axis(2)]
    posting = [_near(2, 0, 0.3)]
    assert assign_postings(candidates, posting, [frozenset({0, 2})]) == [2]


def test_equally_near_candidates_go_to_the_better_ranked() -> None:
    posting = [_near(0, 1, 1.0)]
    assert assign_postings([_axis(1), _axis(0)], posting, [NO_TITLE_HITS]) == [0]
    assert assign_postings([_axis(0), _axis(1)], posting, [frozenset({0, 1})]) == [0]


def test_each_posting_is_an_opening_for_one_candidate_at_most() -> None:
    candidates = [_axis(0), _near(0, 1, 0.1)]
    postings = [_axis(0)] * 3
    assigned = assign_postings(candidates, postings, [NO_TITLE_HITS] * 3)
    assert assigned == [0, 0, 0]


def test_title_hits_must_line_up_with_the_postings() -> None:
    with pytest.raises(ValueError, match="one entry per posting"):
        assign_postings([_axis(0)], [_axis(0), _axis(1)], [NO_TITLE_HITS])


# --- what a search found belongs to the candidate that searched (ADR 0027) ---


def test_a_searched_posting_goes_to_the_candidate_whose_search_found_it() -> None:
    candidates = [_axis(0), _near(0, 1, 0.5)]
    # Nearer the first candidate, but only the second one's search found it.
    posting = [_near(0, 1, 0.4)]
    assert assign_postings(candidates, posting, [NO_TITLE_HITS], searched_by=[frozenset({1})]) == [
        1
    ]


def test_a_searched_posting_irrelevant_to_its_searcher_is_left_out_not_handed_on() -> None:
    candidates = [_axis(0), _axis(1)]
    # Exactly the first candidate's, but the second searched for it, and it is
    # nothing like the second: a loose hit on the description.
    assert assign_postings(
        candidates, [_axis(0)], [NO_TITLE_HITS], searched_by=[frozenset({1})]
    ) == [None]


def test_a_searched_posting_that_names_its_searchers_title_is_relevant() -> None:
    assert assign_postings(
        [_axis(0)], [_axis(5)], [frozenset({0})], searched_by=[frozenset({0})]
    ) == [0]


def test_a_posting_two_searches_found_counts_once_for_the_nearer() -> None:
    candidates = [_axis(0), _axis(1)]
    posting = [_near(1, 0, 0.6)]
    assert assign_postings(
        candidates, posting, [NO_TITLE_HITS], searched_by=[frozenset({0, 1})]
    ) == [1]


def test_a_posting_no_search_found_is_matched_as_before() -> None:
    candidates = [_axis(0), _axis(1)]
    assert assign_postings(
        candidates, [_near(1, 0, 0.2)], [NO_TITLE_HITS], searched_by=[NO_TITLE_HITS]
    ) == [1]


def test_searched_by_must_line_up_with_the_postings() -> None:
    with pytest.raises(ValueError, match="one entry per posting"):
        assign_postings([_axis(0)], [_axis(0)], [NO_TITLE_HITS], searched_by=[])


# --- the ten chosen by a free local estimate (ADR 0027) ----------------------


def test_a_role_whose_openings_read_like_the_strongest_dimension_ranks_first() -> None:
    dimensions = [_axis(0), _axis(1)]
    # Strong in dimension 0, weak in dimension 1.
    weights = [0.9, 0.1]
    roles = [[_axis(1)] * 3, [_axis(0)] * 3]

    estimates = fit_estimates(dimensions, weights, roles, [frozenset({0, 1})] * 2)

    assert estimates[1] > estimates[0]


def test_a_dimension_like_every_role_lifts_none_of_them() -> None:
    broad = [1.0] * 16
    roles = [[_axis(0)] * 3, [_axis(1)] * 3]

    estimates = fit_estimates([broad], [1.0], roles, [frozenset({0})] * 2)

    assert estimates == pytest.approx([0.0, 0.0])


def test_a_dimension_a_candidate_rests_on_counts_more_than_one_it_does_not() -> None:
    dimensions = [_axis(0), _axis(1)]
    roles = [[_axis(0)] * 3, [_axis(1)] * 3]

    cited_first = fit_estimates(dimensions, [0.5, 0.5], roles, [frozenset({0}), frozenset({0})])
    cited_own = fit_estimates(dimensions, [0.5, 0.5], roles, [frozenset({0}), frozenset({1})])

    # Equal strengths: what the candidate rests on decides.
    assert cited_own[1] > cited_first[1]


def test_without_strengths_every_estimate_is_zero() -> None:
    assert fit_estimates([], [], [[_axis(0)]], [NO_TITLE_HITS]) == [0.0]
    assert fit_estimates([_axis(0)], [0.0], [[_axis(0)]], [NO_TITLE_HITS]) == [0.0]


def test_the_ten_are_the_best_estimates_with_the_analysiss_order_breaking_ties() -> None:
    estimates = [0.1, 0.5, 0.5, -0.2, 0.9]
    assert choose_by_estimate(estimates, [0, 1, 2, 4], limit=3) == [4, 1, 2]
    assert choose_by_estimate(estimates, [3], limit=10) == [3]


def test_a_title_hit_on_a_candidate_that_does_not_exist_is_a_bug() -> None:
    with pytest.raises(ValueError, match="does not exist"):
        assign_postings([_axis(0)], [_axis(0)], [frozenset({3})])


def test_a_candidate_in_another_embedding_space_is_a_bug() -> None:
    with pytest.raises(ValueError, match="same length"):
        assign_postings([[1.0, 0.0]], [_axis(0)], [NO_TITLE_HITS])


def test_the_candidates_with_enough_openings_become_roles_in_the_analysiss_order() -> None:
    counts = [5, MIN_POSTINGS_FOR_A_ROLE - 1, MIN_POSTINGS_FOR_A_ROLE, 0, 9]
    assert keep_on_market(counts) == [0, 2, 4]


def test_no_more_candidates_than_the_limit_are_kept() -> None:
    kept = keep_on_market([MIN_POSTINGS_FOR_A_ROLE] * 20, limit=10)
    assert kept == list(range(10))


def test_without_a_limit_every_candidate_on_the_market_is_kept() -> None:
    assert keep_on_market([MIN_POSTINGS_FOR_A_ROLE] * 12) == list(range(12))


def test_a_candidate_the_market_skips_leaves_room_for_the_next() -> None:
    counts = [0] * 3 + [MIN_POSTINGS_FOR_A_ROLE] * 12
    assert keep_on_market(counts, limit=10) == list(range(3, 13))


def test_a_role_needs_an_opening() -> None:
    with pytest.raises(ValueError, match="at least one opening"):
        keep_on_market([1], minimum=0)
