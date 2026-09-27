"""Evidence citation rules and timeline arithmetic."""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from advisor.profile.domain import (
    CitationError,
    CitationHandles,
    Evidence,
    EvidenceGranularity,
    EvidenceSource,
    Position,
    assert_citations_exist,
    total_experience_months,
)


def test_evidence_confidence_must_be_a_probability() -> None:
    with pytest.raises(ValueError, match="between 0 and 1"):
        Evidence.cited(
            owner_id=uuid.uuid4(),
            source=EvidenceSource.GITHUB,
            external_ref="repo",
            reference="repo",
            fact="fact",
            observed_on=date(2026, 1, 1),
            confidence=1.4,
        )


def _fact(**overrides: object) -> Evidence:
    fields: dict[str, object] = {
        "owner_id": uuid.uuid4(),
        "source": EvidenceSource.GITHUB,
        "external_ref": "github:merged:acme/ledger",
        "reference": "GitHub · acme/ledger",
        "fact": "12 merged pull requests authored in acme/ledger.",
        "observed_on": date(2026, 1, 1),
        "confidence": 0.9,
        **overrides,
    }
    return Evidence.cited(**fields)  # type: ignore[arg-type]


def test_a_summary_carries_how_many_items_it_counts() -> None:
    fact = _fact(granularity=EvidenceGranularity.SUMMARY, tally=12, subject="acme/ledger")
    assert (fact.tally, fact.subject) == (12, "acme/ledger")


def test_a_single_item_cannot_claim_a_tally() -> None:
    """A tally on an item would count it as many pieces of work."""
    with pytest.raises(ValueError, match="only a summary"):
        _fact(tally=3)


def test_a_tally_cannot_be_negative() -> None:
    with pytest.raises(ValueError, match="negative"):
        _fact(granularity=EvidenceGranularity.SUMMARY, tally=-1)


def test_a_restated_fact_is_checked_like_a_new_one() -> None:
    fact = _fact()
    with pytest.raises(ValueError, match="only a summary"):
        fact.restate(
            reference=fact.reference,
            fact=fact.fact,
            observed_on=fact.observed_on,
            confidence=fact.confidence,
            granularity=EvidenceGranularity.ITEM,
            tally=12,
            subject=None,
        )


def test_citing_owned_evidence_is_accepted() -> None:
    assert_citations_exist({"e1", "e2"}, {"e1", "e2", "e3"})


def test_citing_evidence_the_user_does_not_have_is_rejected() -> None:
    """An invented citation is how a fabricated resume claim gets in."""
    with pytest.raises(CitationError) as caught:
        assert_citations_exist({"e1", "made-up"}, {"e1", "e2"})
    assert caught.value.invented == frozenset({"made-up"})


def test_citing_another_users_evidence_is_rejected() -> None:
    with pytest.raises(CitationError):
        assert_citations_exist({"other-users-evidence"}, {"e1"})


def test_citing_nothing_is_allowed() -> None:
    assert_citations_exist(set(), {"e1"})


def test_a_current_position_runs_to_today() -> None:
    position = Position("Engineer", "Kestrel", date(2024, 1, 1), None)
    assert position.is_current
    assert position.months(as_of=date(2026, 1, 1)) == 24


def test_overlapping_positions_are_counted_once() -> None:
    """Two concurrent jobs are not twice the experience."""
    positions = [
        Position("Engineer", "Kestrel", date(2023, 1, 1), date(2025, 1, 1)),
        Position("Advisor", "Sidegig", date(2024, 1, 1), date(2024, 7, 1)),
    ]
    assert total_experience_months(positions, as_of=date(2026, 1, 1)) == 24


def test_adjacent_positions_add_up() -> None:
    positions = [
        Position("Junior", "Kestrel", date(2022, 1, 1), date(2023, 1, 1)),
        Position("Senior", "Northwind", date(2023, 1, 1), date(2024, 1, 1)),
    ]
    assert total_experience_months(positions, as_of=date(2026, 1, 1)) == 24


def test_a_gap_between_positions_is_not_counted() -> None:
    positions = [
        Position("Junior", "Kestrel", date(2022, 1, 1), date(2023, 1, 1)),
        Position("Senior", "Northwind", date(2024, 1, 1), date(2025, 1, 1)),
    ]
    assert total_experience_months(positions, as_of=date(2026, 1, 1)) == 24


def test_no_positions_is_no_experience() -> None:
    assert total_experience_months([], as_of=date(2026, 1, 1)) == 0


def test_evidence_is_cited_by_a_short_handle_that_resolves_to_its_id() -> None:
    """A model copying a 36-character id back slips a character; E2 it does not."""
    first, second = uuid.uuid4(), uuid.uuid4()
    handles = CitationHandles([first, second])

    assert (handles.handle(first), handles.handle(second)) == ("E1", "E2")
    assert handles.resolve(["E2", "E1"]) == (str(second), str(first))


def test_a_handle_that_was_never_handed_out_is_an_invented_citation() -> None:
    handles = CitationHandles([uuid.uuid4()])
    with pytest.raises(CitationError) as caught:
        handles.resolve(["E1", "E7"])
    assert caught.value.invented == frozenset({"E7"})


def test_a_raw_id_is_not_a_handle_even_when_the_evidence_is_real() -> None:
    """Resolving is strict: only the names the prompt showed are accepted."""
    real = uuid.uuid4()
    with pytest.raises(CitationError):
        CitationHandles([real]).resolve([str(real)])


def test_an_id_given_no_handle_is_shown_as_itself() -> None:
    gone = uuid.uuid4()
    assert CitationHandles([uuid.uuid4()]).handle(gone) == str(gone)
