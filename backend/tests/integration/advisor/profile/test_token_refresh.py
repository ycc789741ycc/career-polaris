"""A Jira token refreshed during a sync, against a real database.

Atlassian rotates refresh tokens, so the new pair must reach Postgres: the
next sync, in another process, has only what was stored.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from advisor.profile import ProfileService, TokenGrant, create_profile_service
from advisor.profile.domain import ConnectionStatus
from advisor.profile.infra.connectors import Connector, EvidenceDraft
from advisor.profile.infra.oauth import TokenRefresher
from kernel.config import Settings
from kernel.db import Database
from kernel.errors import UpstreamFailedError
from kernel.storage import ObjectStore

pytestmark = pytest.mark.integration


class FakeJira(Connector):
    kind = "jira"
    retired_refs: tuple[str, ...] = ()
    replaced_refs: tuple[str, ...] = ()

    def __init__(self) -> None:
        self.tokens: list[str] = []

    async def account_name(self, client: Any, token: str) -> str:
        return "Ada · acme"

    async def fetch(self, client: Any, token: str) -> list[EvidenceDraft]:
        self.tokens.append(token)
        return [
            EvidenceDraft(
                external_ref="jira:issue:1",
                reference="Jira · ACME-1",
                fact="Closed ACME-1",
                observed_on=date(2026, 9, 1),
            )
        ]


class RotatingRefresher(TokenRefresher):
    def __init__(self, *, refuses: bool = False) -> None:
        self.refuses = refuses
        self.spent: list[str] = []

    async def refresh(self, client: Any, refresh_token: str, *, now: datetime) -> TokenGrant:
        self.spent.append(refresh_token)
        if self.refuses:
            raise UpstreamFailedError("Jira no longer accepts this connection. Reconnect Jira.")
        n = len(self.spent)
        return TokenGrant(
            access_token=f"access-{n}",
            refresh_token=f"refresh-{n}",
            scopes=("read:jira-work",),
            expires_at=now + timedelta(hours=1),
        )


def _profile(
    database: Database, settings: Settings, jira: FakeJira, refresher: RotatingRefresher
) -> ProfileService:
    return create_profile_service(
        database,
        object_store=ObjectStore(settings),
        connectors={"jira": jira},
        token_refreshers={"jira": refresher},
        resume_max_bytes=settings.resume_max_bytes,
        resume_max_pages=settings.resume_max_pages,
        http_timeout_seconds=5,
        user_agent="test",
    )


async def _connect_expired(profile: ProfileService, owner: uuid.UUID) -> None:
    await profile.store_connection(
        owner,
        kind="jira",
        access_token="access-0",
        refresh_token="refresh-0",
        scopes=("read:jira-work",),
        expires_at=datetime.now(UTC) - timedelta(hours=2),
    )


async def test_the_rotated_pair_is_stored_and_used_by_the_next_sync(
    database: Database, settings: Settings, account: uuid.UUID
) -> None:
    jira, refresher = FakeJira(), RotatingRefresher()
    await _connect_expired(_profile(database, settings, jira, refresher), account)

    await _profile(database, settings, jira, refresher).sync_connection(account, "jira")

    # Another process, built fresh, finds the stored token current: no refresh.
    await _profile(database, settings, jira, refresher).sync_connection(account, "jira")

    assert refresher.spent == ["refresh-0"]
    assert jira.tokens == ["access-1", "access-1"]


async def test_a_refused_refresh_leaves_the_connection_failed_with_a_reason(
    database: Database, settings: Settings, account: uuid.UUID
) -> None:
    profile = _profile(database, settings, FakeJira(), RotatingRefresher(refuses=True))
    await _connect_expired(profile, account)

    with pytest.raises(UpstreamFailedError):
        await profile.sync_connection(account, "jira")

    (connection,) = await profile.connections(account)
    assert connection.status == ConnectionStatus.FAILED
    assert "Reconnect Jira" in (connection.last_error or "")
