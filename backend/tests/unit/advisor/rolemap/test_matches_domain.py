"""Ranking the openings inside a user's roles. Pure; no infra."""

from __future__ import annotations

from datetime import date

import pytest

from advisor.rolemap.domain import MAX_MATCHES, MatchCandidate, MatchOrder, rank_matches


def candidate(
    posting: str,
    *,
    fit: int | None,
    role: str = "Backend",
    company: str = "Acme",
    posted_on: date | None = None,
) -> MatchCandidate:
    return MatchCandidate(
        posting_id=posting,
        role_id=role,
        role_name=role,
        company_name=company,
        title=posting,
        fit=fit,
        posted_on=posted_on,
    )


def test_the_newest_come_first_when_asked_and_undated_ones_last() -> None:
    ranked = rank_matches(
        [
            candidate("undated", fit=99),
            candidate("old", fit=90, posted_on=date(2026, 8, 1)),
            candidate("new", fit=40, posted_on=date(2026, 9, 30)),
        ],
        limit=None,
        order=MatchOrder.NEWEST,
    )
    assert [c.posting_id for c in ranked] == ["new", "old", "undated"]


def test_openings_posted_the_same_day_are_broken_the_same_way_every_time() -> None:
    day = date(2026, 9, 1)
    same = [
        candidate("z", fit=10, company="Zeta", posted_on=day),
        candidate("y", fit=90, company="alpha", posted_on=day),
    ]
    first = rank_matches(same, order=MatchOrder.NEWEST)
    assert [c.posting_id for c in first] == ["y", "z"]
    assert rank_matches(list(reversed(same)), order=MatchOrder.NEWEST) == first


def test_the_best_fitting_role_comes_first_and_unscored_roles_last() -> None:
    ranked = rank_matches(
        [
            candidate("a", fit=None),
            candidate("b", fit=62),
            candidate("c", fit=91, role="Platform"),
        ]
    )
    assert [c.posting_id for c in ranked] == ["c", "b", "a"]


def test_ties_are_broken_the_same_way_every_time() -> None:
    same = [
        candidate("z", fit=80, company="Zeta"),
        candidate("y", fit=80, company="alpha"),
        candidate("x", fit=80, company="Alpha", role="Api"),
    ]
    first = rank_matches(same)
    assert [c.posting_id for c in first] == ["x", "y", "z"]
    assert rank_matches(list(reversed(same))) == first


def test_the_list_is_cut_at_the_limit() -> None:
    many = [candidate(str(i), fit=i) for i in range(30)]
    assert [c.fit for c in rank_matches(many, limit=3)] == [29, 28, 27]


def test_without_a_limit_every_opening_is_ranked() -> None:
    """The HTTP list pages the whole ranking, so it asks for all of it,
    past the bound on an explicit limit."""
    many = [candidate(str(i), fit=i) for i in range(MAX_MATCHES + 5)]
    ranked = rank_matches(many, limit=None)
    assert len(ranked) == MAX_MATCHES + 5
    assert ranked[0].fit == MAX_MATCHES + 4


@pytest.mark.parametrize("limit", [0, MAX_MATCHES + 1])
def test_a_limit_outside_the_bound_is_refused(limit: int) -> None:
    with pytest.raises(ValueError, match="between"):
        rank_matches([], limit=limit)


# -- one per company: "Top matched" across all roles --------------------------


def test_one_per_company_keeps_each_companys_best_opening() -> None:
    ranked = rank_matches(
        [
            candidate("g2i-low", fit=60, company="G2i"),
            candidate("g2i-high", fit=95, company="G2i"),
            candidate("acme", fit=80, company="Acme"),
        ],
        one_per_company=True,
    )
    assert [c.posting_id for c in ranked] == ["g2i-high", "acme"]


def test_one_per_company_fills_the_limit_from_other_companies() -> None:
    many = [candidate(f"g2i-{i}", fit=95, company="G2i") for i in range(5)]
    others = [candidate(f"other-{i}", fit=50, company=f"Company {i}") for i in range(3)]

    ranked = rank_matches([*many, *others], limit=3, one_per_company=True)

    assert [c.company_name for c in ranked] == ["G2i", "Company 0", "Company 1"]


def test_a_company_is_the_same_whatever_its_case_or_spacing() -> None:
    ranked = rank_matches(
        [candidate("a", fit=90, company="G2i"), candidate("b", fit=80, company=" g2i ")],
        one_per_company=True,
    )
    assert [c.posting_id for c in ranked] == ["a"]


def test_without_the_rule_a_company_may_repeat() -> None:
    ranked = rank_matches(
        [candidate("a", fit=90, company="G2i"), candidate("b", fit=80, company="G2i")]
    )
    assert [c.posting_id for c in ranked] == ["a", "b"]
