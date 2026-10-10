"""The rules of choosing which key AI runs on (ADR 0064)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from advisor.identity.domain import (
    AiSource,
    AiSourceChoice,
    AiSourceRefusal,
    AiSourceStanding,
    get_choice_refusal,
    get_source_in_use,
)

READY = AiSourceStanding(has_credential=True, is_platform_on=True, is_eligible=True)


@pytest.mark.parametrize(
    ("standing", "accepted", "refusal"),
    [
        (READY, True, None),
        (AiSourceStanding(True, False, True), True, AiSourceRefusal.PLATFORM_OFF),
        (AiSourceStanding(True, True, False), True, AiSourceRefusal.NOT_ELIGIBLE),
        (READY, False, AiSourceRefusal.TERMS_NOT_ACCEPTED),
    ],
)
def test_the_platform_needs_it_on_a_google_account_and_the_terms_accepted(
    standing: AiSourceStanding, accepted: bool, refusal: AiSourceRefusal | None
) -> None:
    assert get_choice_refusal(AiSource.PLATFORM, standing, has_accepted_terms=accepted) is refusal


def test_ones_own_key_needs_only_a_stored_credential() -> None:
    no_key = AiSourceStanding(has_credential=False, is_platform_on=False, is_eligible=False)
    assert get_choice_refusal(AiSource.OWN, READY, has_accepted_terms=False) is None
    assert (
        get_choice_refusal(AiSource.OWN, no_key, has_accepted_terms=False)
        is AiSourceRefusal.NO_CREDENTIAL
    )


def test_nothing_chosen_never_means_the_platform() -> None:
    """Choosing it is when the user accepts where their evidence goes."""
    no_key = AiSourceStanding(has_credential=False, is_platform_on=True, is_eligible=True)
    assert get_source_in_use(None, READY) is AiSource.OWN
    assert get_source_in_use(None, no_key) is None


def test_the_terms_once_accepted_stay_accepted() -> None:
    choice = AiSourceChoice.create_choice(uuid.uuid4(), AiSource.OWN)
    first = datetime(2026, 10, 1, tzinfo=UTC)

    choice.update_source(AiSource.PLATFORM, terms_accepted_at=first)
    choice.update_source(AiSource.OWN, terms_accepted_at=None)
    choice.update_source(AiSource.PLATFORM, terms_accepted_at=datetime(2026, 10, 9, tzinfo=UTC))

    assert choice.source is AiSource.PLATFORM
    assert choice.platform_terms_accepted_at == first
