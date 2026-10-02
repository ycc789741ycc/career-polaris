"""A role's name is one job title: where or how it is worked is not part of
it, whatever the model that named it said (Phase 8)."""

from __future__ import annotations

import pytest

from advisor.rolemap.domain import parse_role_name


@pytest.mark.parametrize(
    ("named", "shown"),
    [
        ("Senior Data Scientist / AI Engineer (Remote)", "Senior Data Scientist / AI Engineer"),
        ("Senior Data Scientist (m/f/x)", "Senior Data Scientist"),
        ("Backend Engineer - Remote", "Backend Engineer"),
        ("Data Engineer (Remote, US) [m/w/d]", "Data Engineer"),
        ("Platform Engineer, Hybrid", "Platform Engineer"),
        ("Site Reliability Engineer (On-site)", "Site Reliability Engineer"),
        ("Senior Data Scientist (100% Remote)", "Senior Data Scientist"),
        ("  Staff Engineer  ", "Staff Engineer"),
    ],
)
def test_a_work_arrangement_or_gender_tag_is_taken_off_the_end(named: str, shown: str) -> None:
    assert parse_role_name(named) == shown


@pytest.mark.parametrize(
    "named",
    [
        "Engineer, Hybrid Cloud",
        "Data Scientist (Ads)",
        "Remote Sensing Analyst",
        "Remote",
    ],
)
def test_a_name_the_tag_is_part_of_or_all_of_is_kept(named: str) -> None:
    assert parse_role_name(named) == named
