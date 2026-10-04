"""Whether the worker and the crawler are up: plain values, so the components
that read them never reach the database package (ADR 0052)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class UnitPresence:
    """One kind of process. ``online_since`` is when the earliest one still
    beating started; None while none is. ``seen_at`` is the last beat of any."""

    online_since: datetime | None
    seen_at: datetime | None

    @property
    def is_online(self) -> bool:
        return self.online_since is not None


@dataclass(frozen=True, slots=True)
class PresenceView:
    worker: UnitPresence
    crawler: UnitPresence
