"""Which key a user's AI runs on: their own, or the platform's (ADR 0064).

The user chooses, and may switch back and forth. The platform's key is only
for an account Google has verified, only while the operator has it switched
on, and only once the user has accepted that their evidence goes to the
operator's provider account. Nothing falls back from one to the other.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class AiSource(StrEnum):
    OWN = "own"
    PLATFORM = "platform"


class AiSourceRefusal(StrEnum):
    """Why a choice cannot be made. Stable: the service maps these to errors."""

    NO_CREDENTIAL = "no_credential"
    PLATFORM_OFF = "platform_off"
    NOT_ELIGIBLE = "not_eligible"
    TERMS_NOT_ACCEPTED = "terms_not_accepted"


@dataclass(frozen=True, slots=True)
class AiSourceStanding:
    """What the choice is made against."""

    has_credential: bool
    is_platform_on: bool
    # Google has verified this account's address.
    is_eligible: bool


@dataclass(slots=True)
class AiSourceChoice:
    id: uuid.UUID
    owner_id: uuid.UUID
    source: AiSource
    # When the user accepted that the platform's provider sees their
    # evidence. Kept once given, so switching back needs no second notice.
    platform_terms_accepted_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def create_choice(cls, owner_id: uuid.UUID, source: AiSource) -> AiSourceChoice:
        return cls(id=uuid.uuid4(), owner_id=owner_id, source=source)

    def update_source(self, source: AiSource, *, terms_accepted_at: datetime | None) -> None:
        self.source = source
        if self.platform_terms_accepted_at is None and terms_accepted_at is not None:
            self.platform_terms_accepted_at = terms_accepted_at


def get_choice_refusal(
    source: AiSource,
    standing: AiSourceStanding,
    *,
    has_accepted_terms: bool,
) -> AiSourceRefusal | None:
    """Why ``source`` cannot be chosen now, or None when it can."""
    if source is AiSource.OWN:
        return None if standing.has_credential else AiSourceRefusal.NO_CREDENTIAL
    if not standing.is_platform_on:
        return AiSourceRefusal.PLATFORM_OFF
    if not standing.is_eligible:
        return AiSourceRefusal.NOT_ELIGIBLE
    if not has_accepted_terms:
        return AiSourceRefusal.TERMS_NOT_ACCEPTED
    return None


def get_source_in_use(choice: AiSourceChoice | None, standing: AiSourceStanding) -> AiSource | None:
    """The key a call runs on now, or None when there is none to run on.

    With no choice made, the user's own key if they stored one: the
    platform's is never taken without the user choosing it, because choosing
    it is when they accept where their evidence goes.
    """
    if choice is None:
        return AiSource.OWN if standing.has_credential else None
    return choice.source
