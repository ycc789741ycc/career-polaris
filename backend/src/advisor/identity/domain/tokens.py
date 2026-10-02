"""Session token rules.

We issue our own tokens rather than delegating to a provider, so the shape of a
session is a domain decision:

* A short-lived **access token** is what every API request carries. It is held
  in the client's memory and never written to storage the browser can read.
* A long-lived **refresh token** is what survives a reload. It goes in an
  httpOnly cookie, so a cross-site scripting bug cannot read it.

Refresh tokens **rotate**: using one issues a replacement and retires the old.
That turns a stolen token into something detectable — if a retired token is
presented, the family is compromised and the whole chain is revoked.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from advisor.identity.domain.constants import REFRESH_TOKEN_BYTES


class TokenKind(StrEnum):
    ACCESS = "access"
    REFRESH = "refresh"


class RefreshRejectedError(Exception):
    """A refresh token was presented that must not be honoured."""


@dataclass(frozen=True, slots=True)
class RefreshTokenState:
    expires_at: datetime
    revoked_at: datetime | None
    used_at: datetime | None

    def assert_usable(self, *, now: datetime) -> None:
        if self.revoked_at is not None:
            raise RefreshRejectedError("this session was signed out")
        if self.used_at is not None:
            # Rotation means a token is single-use. Seeing one twice means
            # either a replay or a stolen copy, and we cannot tell which — so
            # the caller revokes the whole family.
            raise RefreshRejectedError("this refresh token was already used")
        if now >= self.expires_at:
            raise RefreshRejectedError("this session expired; sign in again")


def new_refresh_token() -> str:
    return secrets.token_urlsafe(REFRESH_TOKEN_BYTES)


def access_token_expiry(*, now: datetime, ttl_seconds: int) -> datetime:
    return now + timedelta(seconds=ttl_seconds)


def refresh_token_expiry(*, now: datetime, ttl_days: int) -> datetime:
    return now + timedelta(days=ttl_days)


def digest(token: str) -> str:
    """Refresh tokens are stored hashed.

    SHA-256 rather than Argon2 on purpose: the token is 32 random bytes, so
    there is no guessing to slow down — only a stored value to keep useless if
    the database leaks.
    """
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass(slots=True)
class RefreshToken:
    """One issued refresh token, held only as a digest.

    ``family_id`` ties a rotation chain together, so a reused token can take
    the whole chain down with it.
    """

    id: uuid.UUID
    account_id: uuid.UUID
    token_hash: str
    family_id: uuid.UUID
    expires_at: datetime
    used_at: datetime | None = None
    revoked_at: datetime | None = None
    created_at: datetime | None = None

    @classmethod
    def issued(
        cls,
        account_id: uuid.UUID,
        *,
        token_hash: str,
        family_id: uuid.UUID,
        expires_at: datetime,
    ) -> RefreshToken:
        return cls(
            id=uuid.uuid4(),
            account_id=account_id,
            token_hash=token_hash,
            family_id=family_id,
            expires_at=expires_at,
        )

    @property
    def state(self) -> RefreshTokenState:
        return RefreshTokenState(
            expires_at=self.expires_at, revoked_at=self.revoked_at, used_at=self.used_at
        )

    def use(self, at: datetime) -> None:
        """Single-use: rotation spends a token the moment it is exchanged."""
        self.used_at = at
