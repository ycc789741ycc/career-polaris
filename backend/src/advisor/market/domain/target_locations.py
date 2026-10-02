"""The places a user wants to work, chosen from the list in ``places``
(domain decision 21, ADR 0026).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from advisor.market.domain.constants import (
    MAX_TARGET_LOCATION,
    MAX_TARGET_LOCATIONS,
)
from advisor.market.domain.places import target_location_option


class TargetLocationError(ValueError):
    """A set of target locations the market cannot scope by."""


def chosen_target_locations(values: Sequence[str]) -> tuple[str, ...]:
    """The user's target locations as they will be stored: each one a listed
    place under its own name ("united kingdom" is "United Kingdom"), named once,
    in the order given, and at most three."""
    chosen: list[str] = []
    for raw in values:
        value = raw.strip()
        if not value:
            raise TargetLocationError("a target location cannot be blank")
        if len(value) > MAX_TARGET_LOCATION:
            raise TargetLocationError(
                f"a target location is at most {MAX_TARGET_LOCATION} characters"
            )
        option = target_location_option(value)
        if option is None:
            raise TargetLocationError(f"{value!r} is not a place on the list")
        if option.name not in chosen:
            chosen.append(option.name)
    if len(chosen) > MAX_TARGET_LOCATIONS:
        raise TargetLocationError(
            f"choose at most {MAX_TARGET_LOCATIONS} target locations, got {len(chosen)}"
        )
    return tuple(chosen)


@dataclass(slots=True)
class MarketPreference:
    """One of the user's target locations (domain decision 21). The name is the
    table's, ``market_user.market_preference``, which predates the term."""

    id: uuid.UUID
    owner_id: uuid.UUID
    market: str
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def chosen(cls, *, owner_id: uuid.UUID, market: str) -> MarketPreference:
        return cls(id=uuid.uuid4(), owner_id=owner_id, market=market)
