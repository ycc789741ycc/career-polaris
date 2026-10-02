"""Pay read out of a posting's text. Pure — no crawler, no database."""

from __future__ import annotations

import pytest

from advisor.market.domain import SalaryRange, salary_in_text, yearly_range


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # GitLab's wording, with the entity Greenhouse leaves in its content.
        (
            "United States Salary Range $139,200 &mdash; $235,200 USD How GitLab Supports",
            SalaryRange(139_200, 235_200, "USD"),
        ),
        ("The base salary is €80k\u201395k, plus equity.", SalaryRange(80_000, 95_000, "EUR")),
        ("£60,000 - £75,000 per annum", SalaryRange(60_000, 75_000, "GBP")),
        ("Pay: 120.000 € - 150.000 €", SalaryRange(120_000, 150_000, "EUR")),
        ("between $150,000.00 and $180,000.00 a year", SalaryRange(150_000, 180_000, "USD")),
        ("CA$120,000 to CA$150,000", SalaryRange(120_000, 150_000, "CAD")),
        ("USD 130K - 160K", SalaryRange(130_000, 160_000, "USD")),
        ("$80,000 - $95.5k", SalaryRange(80_000, 95_500, "USD")),
    ],
)
def test_a_stated_yearly_range_is_read(text: str, expected: SalaryRange) -> None:
    assert salary_in_text(text) == expected


def test_a_written_currency_code_wins_over_the_dollar_sign() -> None:
    found = salary_in_text("$120,000 - $150,000 CAD")
    assert found is not None and found.currency == "CAD"


def test_the_first_range_is_taken_when_several_regions_are_listed() -> None:
    text = "US: $150,000 - $200,000 USD. UK: £90,000 - £120,000 GBP."
    assert salary_in_text(text) == SalaryRange(150_000, 200_000, "USD")


def test_a_later_yearly_range_is_found_past_an_hourly_one() -> None:
    text = "Interns earn $40 - $55 per hour. Engineers: $140,000 - $170,000."
    assert salary_in_text(text) == SalaryRange(140_000, 170_000, "USD")


@pytest.mark.parametrize(
    "text",
    [
        "",
        "Build the ledger API in Go.",
        "We raised $100M - $200M from investors.",
        "Contractors are paid $12,000 - $15,000 per month.",
        "The team grew 2019 - 2024.",
        "A 401(k) match of 3 - 6 percent.",
        "Salary: 120,000 - 150,000",  # no currency, so not a salary we can band
        "Signing bonus $2,000 - $5,000",  # too small to be a yearly salary
        "$200,000 - $150,000",  # backwards
    ],
)
def test_text_without_a_yearly_range_yields_nothing(text: str) -> None:
    assert salary_in_text(text) is None


@pytest.mark.parametrize("period", [None, "", "per-year-salary", "1 YEAR", "YEAR", "annual"])
def test_a_range_stated_yearly_or_with_no_period_is_a_years_pay(period: str | None) -> None:
    assert yearly_range(80_000, 95_000, "EUR", period=period) == SalaryRange(80_000, 95_000, "EUR")


@pytest.mark.parametrize("period", ["per-hour-wage", "1 HOUR", "MONTH", "monthly", "WEEK"])
def test_a_range_stated_for_any_other_period_is_dropped_not_converted(period: str) -> None:
    assert yearly_range(80_000, 95_000, "EUR", period=period) is None


@pytest.mark.parametrize(("low", "high"), [(45, 60), (9_000, 12_000), (90_000, 200_000_000)])
def test_an_amount_no_years_pay_could_be_is_dropped(low: int, high: int) -> None:
    assert yearly_range(low, high, "USD") is None
