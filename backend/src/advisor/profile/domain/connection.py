"""A connected source of evidence: GitHub or Jira, and its sync state."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


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
    ) -> None:
        """New tokens clear any earlier failure."""
        self.encrypted_access_token = encrypted_access_token
        self.encrypted_refresh_token = encrypted_refresh_token
        self.scopes = scopes
        self.token_expires_at = expires_at
        self.external_account = account
        self.status = ConnectionStatus.CONNECTED
        self.last_error = None

    @property
    def is_syncing(self) -> bool:
        return self.sync_started_at is not None

    def sync_requested(self, at: datetime) -> None:
        self.sync_started_at = at

    def sync_failed(self, error: str) -> None:
        self.status = ConnectionStatus.FAILED
        self.last_error = error
        self.sync_started_at = None

    def synced(self, at: datetime, *, account: str) -> None:
        """A sync also refreshes whose account this is, in case it was renamed."""
        self.sync_started_at = None
        self.last_synced_at = at
        self.external_account = account
        self.status = ConnectionStatus.CONNECTED
        self.last_error = None
