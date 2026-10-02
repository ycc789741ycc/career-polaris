"""A version of the career profile, so an analysis says which facts it read."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class ProfileVersion:
    """Bumped whenever evidence changes, so a report computed from an older
    version can be detected as stale rather than shown as current."""

    id: uuid.UUID
    owner_id: uuid.UUID
    version: int
    updated_at: datetime

    @classmethod
    def first(cls, *, owner_id: uuid.UUID, at: datetime) -> ProfileVersion:
        return cls(id=uuid.uuid4(), owner_id=owner_id, version=1, updated_at=at)

    def bump(self, at: datetime) -> None:
        self.version += 1
        self.updated_at = at
