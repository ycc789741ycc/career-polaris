"""A connected source of evidence: GitHub or Jira, and its sync state."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from advisor.profile.domain.constants import TOKEN_REFRESH_MARGIN_SECONDS


class ConnectionStatus(StrEnum):
    CONNECTED = "connected"
    FAILED = "failed"


@dataclass(slots=True)
class SourceConnection:
    """An authorised link to GitHub or Jira.

    The tokens are held encrypted; only the worker's ``sync`` queue opens them.
    """

    id: uuid.UUID
    owner_id: uuid.UUID
    kind: str
    external_account: str | None
    encrypted_access_token: str
    encrypted_refresh_token: str | None
    scopes: tuple[str, ...]
    status: ConnectionStatus
    last_error: str | None = None
    last_synced_at: datetime | None = None
    token_expires_at: datetime | None = None
    # Set when a sync is queued and cleared when it ends either way, so the page
    # can show the sync running and an analysis can wait for it (ADR 0018).
    sync_started_at: datetime | None = None
    # The provider's id for the account, where we report on it (Atlassian's
    # accountId, ADR 0061). None for GitHub.
    external_account_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def new(cls, *, owner_id: uuid.UUID, kind: str) -> SourceConnection:
        return cls(
            id=uuid.uuid4(),
            owner_id=owner_id,
            kind=kind,
            external_account=None,
            encrypted_access_token="",
            encrypted_refresh_token=None,
            scopes=(),
            status=ConnectionStatus.CONNECTED,
        )

    def authorise(
        self,
        *,
        encrypted_access_token: str,
        encrypted_refresh_token: str | None,
        scopes: tuple[str, ...],
        expires_at: datetime | None,
        account: str | None,
        account_id: str | None = None,
    ) -> None:
        """New tokens clear any earlier failure."""
        self.encrypted_access_token = encrypted_access_token
        self.encrypted_refresh_token = encrypted_refresh_token
        self.scopes = scopes
        self.token_expires_at = expires_at
        self.external_account = account
        self.external_account_id = account_id
        self.status = ConnectionStatus.CONNECTED
        self.last_error = None

    def update_tokens(
        self,
        *,
        encrypted_access_token: str,
        encrypted_refresh_token: str | None,
        expires_at: datetime | None,
    ) -> None:
        """A refreshed pair replaces the old one; the account stays as it was.

        Atlassian rotates refresh tokens, so the old one is spent: keeping it
        when no new one came back would only fail the next refresh later.
        """
        self.encrypted_access_token = encrypted_access_token
        self.encrypted_refresh_token = encrypted_refresh_token
        self.token_expires_at = expires_at

    def is_token_expiring(self, at: datetime) -> bool:
        """Whether the access token runs out within the refresh margin.

        A token with no known expiry (GitHub's) never needs refreshing.
        """
        if self.token_expires_at is None:
            return False
        margin = timedelta(seconds=TOKEN_REFRESH_MARGIN_SECONDS)
        return self.token_expires_at - margin <= at

    @property
    def is_syncing(self) -> bool:
        return self.sync_started_at is not None

    def sync_requested(self, at: datetime) -> None:
        self.sync_started_at = at

    def sync_failed(self, error: str) -> None:
        self.status = ConnectionStatus.FAILED
        self.last_error = error
        self.sync_started_at = None

    def synced(self, at: datetime, *, account: str, account_id: str | None = None) -> None:
        """A sync also refreshes whose account this is, in case it was renamed."""
        self.sync_started_at = None
        self.last_synced_at = at
        self.external_account = account
        self.external_account_id = account_id
        self.status = ConnectionStatus.CONNECTED
        self.last_error = None
