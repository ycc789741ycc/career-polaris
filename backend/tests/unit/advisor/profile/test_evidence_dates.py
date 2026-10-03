"""What a fact's date means, as every prompt shows it (ADR 0037): when the work
happened, the newest item of a tally, or when the fact was stated."""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from advisor.profile import EvidenceSource, EvidenceView, get_evidence_line
from advisor.profile.domain import EvidenceGranularity, get_date_label

DAY = date(2026, 8, 14)


def _fact(
    source: EvidenceSource,
    *,
    observed_on: date | None = DAY,
    granularity: EvidenceGranularity = EvidenceGranularity.ITEM,
    stated_on: date | None = None,
) -> EvidenceView:
    return EvidenceView(
        id=uuid.uuid4(),
        source=source,
        reference="GitHub · ledger@abc1234",
        fact="Split ledger reads from writes",
        observed_on=observed_on,
        granularity=granularity,
        tally=3 if granularity is EvidenceGranularity.SUMMARY else None,
        subject=None,
        stated_on=stated_on,
    )


@pytest.mark.parametrize(
    ("fact", "label"),
    [
        (_fact(EvidenceSource.GITHUB), "2026-08-14"),
        (_fact(EvidenceSource.JIRA, granularity=EvidenceGranularity.SUMMARY), "latest 2026-08-14"),
        (
            _fact(EvidenceSource.RESUME, observed_on=None, stated_on=date(2026, 5, 2)),
            "from a résumé uploaded 2026-05-02",
        ),
        (_fact(EvidenceSource.USER_ANSWER, observed_on=date(2026, 9, 30)), "answered 2026-09-30"),
        (_fact(EvidenceSource.GITHUB, observed_on=None), "undated"),
        # A résumé line is dated by its upload, never by anything else.
        (_fact(EvidenceSource.RESUME, observed_on=DAY), "undated"),
    ],
)
def test_each_kind_of_date_says_what_it_means(fact: EvidenceView, label: str) -> None:
    assert (
        get_date_label(
            source=fact.source,
            granularity=fact.granularity,
            observed_on=fact.observed_on,
            stated_on=fact.stated_on,
        )
        == label
    )
    assert get_evidence_line(fact) == (
        f"({fact.source}, {label}) GitHub · ledger@abc1234: Split ledger reads from writes"
    )


def test_a_citable_line_leads_with_its_handle() -> None:
    line = get_evidence_line(_fact(EvidenceSource.GITHUB), "E3")

    assert line.startswith("[E3] (github, 2026-08-14) ")


def test_a_fact_is_ordered_by_the_date_it_is_shown_with() -> None:
    resume = _fact(EvidenceSource.RESUME, observed_on=None, stated_on=date(2026, 5, 2))

    assert resume.shown_on == date(2026, 5, 2)
    assert _fact(EvidenceSource.GITHUB).shown_on == DAY
    assert _fact(EvidenceSource.GITHUB, observed_on=None).shown_on is None
