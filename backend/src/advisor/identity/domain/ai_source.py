"""Which key a user's AI runs on: their own, or the platform's (ADR 0064).

The platform's key is only for an account Google has verified, and only while
the operator has it switched on. Such an account runs on it until it chooses
otherwise (ADR 0066); storing a key of one's own chooses that. The user may
switch back and forth, and nothing falls back from one to the other.
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
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def create_choice(cls, owner_id: uuid.UUID, source: AiSource) -> AiSourceChoice:
        return cls(id=uuid.uuid4(), owner_id=owner_id, source=source)

    def update_source(self, source: AiSource) -> None:
        self.source = source


def get_choice_refusal(source: AiSource, standing: AiSourceStanding) -> AiSourceRefusal | None:
    """Why ``source`` cannot be chosen now, or None when it can."""
    if source is AiSource.OWN:
        return None if standing.has_credential else AiSourceRefusal.NO_CREDENTIAL
    if not standing.is_platform_on:
        return AiSourceRefusal.PLATFORM_OFF
    if not standing.is_eligible:
        return AiSourceRefusal.NOT_ELIGIBLE
    return None


def get_source_in_use(choice: AiSourceChoice | None, standing: AiSourceStanding) -> AiSource | None:
    """The key a call runs on now, or None when there is none to run on.

    With no choice made, the platform's for an eligible account while it is
    on, so a new Google user starts with nothing to set up (ADR 0066);
    otherwise the user's own key if they stored one.
    """
    if choice is not None:
        return choice.source
    if standing.is_platform_on and standing.is_eligible:
        return AiSource.PLATFORM
    return AiSource.OWN if standing.has_credential else None
