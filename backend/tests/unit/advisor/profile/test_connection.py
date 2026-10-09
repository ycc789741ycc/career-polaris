"""When a connection's access token needs refreshing, and what a refresh keeps."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from advisor.profile.domain import SourceConnection

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)


def _connection(expires_at: datetime | None) -> SourceConnection:
    connection = SourceConnection.new(owner_id=uuid.uuid4(), kind="jira")
    connection.authorise(
        encrypted_access_token="old-access",
        encrypted_refresh_token="old-refresh",
        scopes=("read:jira-work",),
        expires_at=expires_at,
        account="Ada · acme",
    )
    return connection


def test_a_token_with_no_known_expiry_never_needs_refreshing() -> None:
    assert not _connection(None).is_token_expiring(NOW)


def test_a_token_with_time_to_spare_is_used_as_it_is() -> None:
    assert not _connection(NOW + timedelta(minutes=30)).is_token_expiring(NOW)


def test_a_token_about_to_run_out_is_refreshed_before_a_sync() -> None:
    assert _connection(NOW + timedelta(minutes=2)).is_token_expiring(NOW)


def test_an_expired_token_is_refreshed() -> None:
    assert _connection(NOW - timedelta(hours=3)).is_token_expiring(NOW)


def test_a_refresh_replaces_both_tokens_and_keeps_the_account() -> None:
    connection = _connection(NOW)

    connection.update_tokens(
        encrypted_access_token="new-access",
        encrypted_refresh_token="new-refresh",
        expires_at=NOW + timedelta(hours=1),
    )

    assert connection.encrypted_access_token == "new-access"
    assert connection.encrypted_refresh_token == "new-refresh"
    assert connection.token_expires_at == NOW + timedelta(hours=1)
    assert connection.external_account == "Ada · acme"
