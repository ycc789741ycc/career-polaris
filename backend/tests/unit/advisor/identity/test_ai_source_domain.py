"""The rules of choosing which key AI runs on (ADR 0064)."""

from __future__ import annotations

import uuid

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
    ("standing", "refusal"),
    [
        (READY, None),
        (AiSourceStanding(True, False, True), AiSourceRefusal.PLATFORM_OFF),
        (AiSourceStanding(True, True, False), AiSourceRefusal.NOT_ELIGIBLE),
    ],
)
def test_the_platform_needs_it_on_and_a_google_account(
    standing: AiSourceStanding, refusal: AiSourceRefusal | None
) -> None:
    assert get_choice_refusal(AiSource.PLATFORM, standing) is refusal


def test_ones_own_key_needs_only_a_stored_credential() -> None:
    no_key = AiSourceStanding(has_credential=False, is_platform_on=False, is_eligible=False)
    assert get_choice_refusal(AiSource.OWN, READY) is None
    assert get_choice_refusal(AiSource.OWN, no_key) is AiSourceRefusal.NO_CREDENTIAL


@pytest.mark.parametrize(
    ("standing", "source"),
    [
        # Eligible while the platform is on: it, key or no key (ADR 0066).
        (READY, AiSource.PLATFORM),
        (AiSourceStanding(False, True, True), AiSource.PLATFORM),
        # Otherwise the user's own key, if they stored one.
        (AiSourceStanding(True, True, False), AiSource.OWN),
        (AiSourceStanding(True, False, True), AiSource.OWN),
        (AiSourceStanding(False, False, True), None),
        (AiSourceStanding(False, True, False), None),
    ],
)
def test_with_nothing_chosen_an_eligible_account_runs_on_the_platform(
    standing: AiSourceStanding, source: AiSource | None
) -> None:
    assert get_source_in_use(None, standing) is source


def test_a_choice_made_is_what_runs() -> None:
    choice = AiSourceChoice.create_choice(uuid.uuid4(), AiSource.PLATFORM)
    choice.update_source(AiSource.OWN)

    assert get_source_in_use(choice, READY) is AiSource.OWN
