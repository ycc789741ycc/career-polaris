"""What the market tells the rest of the system, as domain facts.

How an event is delivered (the transactional outbox) is infrastructure;
``advisor.market.infra`` maps each of these to its outbox name and payload.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TargetLocationsChanged:
    """The user's target locations after a change: the whole set, since it is
    the set that scopes their role map."""

    owner_id: uuid.UUID
    locations: tuple[str, ...]


MarketEvent = TargetLocationsChanged
