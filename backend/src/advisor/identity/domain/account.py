"""An account: who signs in. How they sign in lives with each way to do it
(``password``, ``federated``, ``tokens``).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class Account:
    """A person using the app, and the subject of the tokens we issue.

    ``email`` is stored normalised, so there is one account per address.
    """

    id: uuid.UUID
    email: str
    background_jobs_paused_at: datetime | None = None
    paused_reason: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def registered(cls, email: str) -> Account:
        return cls(id=uuid.uuid4(), email=email)

    def pause_background_jobs(self, reason: str, *, at: datetime) -> None:
        """A failed key or an exhausted budget pauses scheduled work, so
        nothing silently runs up a bill or goes stale."""
        self.background_jobs_paused_at = at
        self.paused_reason = reason

    def resume_background_jobs(self) -> None:
        self.background_jobs_paused_at = None
        self.paused_reason = None
