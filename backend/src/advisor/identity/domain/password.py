"""Password rules: lockout and the stored credential.

Pure, so it is testable without a database and without hashing anything. The
hashing itself is infrastructure and lives in ``infra/passwords.py``. No
password is set any more (ADR 0080), so there is no strength policy: only
accounts from before then sign in with one.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from advisor.identity.domain.constants import (
    LOCKOUT_WINDOW,
    MAX_FAILED_ATTEMPTS,
)

# --- brute-force resistance -------------------------------------------------


@dataclass(frozen=True, slots=True)
class LockoutState:
    failed_attempts: int
    last_failed_at: datetime | None

    def is_locked(self, *, now: datetime) -> bool:
        """Locked once the attempts run out, until the window passes.

        Time-based rather than permanent: a permanent lock turns a guessing
        attempt against someone else into a way to lock them out of their own
        account.
        """
        if self.failed_attempts < MAX_FAILED_ATTEMPTS or self.last_failed_at is None:
            return False
        return now - self.last_failed_at < LOCKOUT_WINDOW

    def unlocks_at(self, *, now: datetime) -> datetime | None:
        if not self.is_locked(now=now) or self.last_failed_at is None:
            return None
        return self.last_failed_at + LOCKOUT_WINDOW

    def after_failure(self, *, now: datetime) -> LockoutState:
        # A failure after the window has passed starts the count again.
        expired = self.last_failed_at is not None and now - self.last_failed_at >= LOCKOUT_WINDOW
        base = 0 if expired else self.failed_attempts
        return LockoutState(failed_attempts=base + 1, last_failed_at=now)

    def after_success(self) -> LockoutState:
        return LockoutState(failed_attempts=0, last_failed_at=None)


def normalize_email(email: str) -> str:
    """One account per address, however it was typed."""
    return email.strip().lower()


@dataclass(slots=True)
class PasswordCredential:
    id: uuid.UUID
    account_id: uuid.UUID
    password_hash: str
    failed_attempts: int
    last_failed_at: datetime | None
    password_updated_at: datetime
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def set_for(
        cls, account_id: uuid.UUID, *, password_hash: str, at: datetime
    ) -> PasswordCredential:
        return cls(
            id=uuid.uuid4(),
            account_id=account_id,
            password_hash=password_hash,
            failed_attempts=0,
            last_failed_at=None,
            password_updated_at=at,
        )

    @property
    def lockout(self) -> LockoutState:
        return LockoutState(
            failed_attempts=self.failed_attempts, last_failed_at=self.last_failed_at
        )

    def record_lockout(self, state: LockoutState) -> None:
        self.failed_attempts = state.failed_attempts
        self.last_failed_at = state.last_failed_at

    def rehash(self, password_hash: str, *, at: datetime) -> None:
        self.password_hash = password_hash
        self.password_updated_at = at
