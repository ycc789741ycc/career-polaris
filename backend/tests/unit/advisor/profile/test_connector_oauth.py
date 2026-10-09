"""Connector OAuth state: signed, scoped to one user, and short-lived."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from advisor.profile.infra.oauth import (
    STATE_TTL_SECONDS,
    OAuthTokenRefresher,
    authorize_url,
    endpoints_for,
    parse_token_grant,
    sign_state,
    verify_state,
)
from kernel.errors import UnauthenticatedError, UpstreamFailedError, ValidationError

SECRET = "test-signing-secret"
JIRA_BASE = "https://auth.atlassian.com"
OWNER = uuid.UUID("11111111-1111-1111-1111-111111111111")


def test_state_round_trips_to_its_user_and_connector() -> None:
    state = sign_state(OWNER, "github", secret=SECRET)
    assert verify_state(state, secret=SECRET) == (OWNER, "github")


def test_state_signed_with_another_secret_is_refused() -> None:
    state = sign_state(OWNER, "github", secret=SECRET)
    with pytest.raises(UnauthenticatedError, match="does not verify"):
        verify_state(state, secret="a-different-secret")


def test_a_tampered_state_is_refused() -> None:
    """Swapping the user in the payload must not survive the signature."""
    state = sign_state(OWNER, "github", secret=SECRET)
    _payload, signature = state.split(".", 1)
    forged = sign_state(uuid.uuid4(), "github", secret="attacker").split(".", 1)[0]
    with pytest.raises(UnauthenticatedError):
        verify_state(f"{forged}.{signature}", secret=SECRET)


def test_an_expired_state_is_refused() -> None:
    state = sign_state(OWNER, "github", secret=SECRET, now=1_000_000)
    with pytest.raises(UnauthenticatedError, match="expired"):
        verify_state(state, secret=SECRET, now=1_000_000 + STATE_TTL_SECONDS + 1)


def test_a_state_just_inside_the_window_is_accepted() -> None:
    state = sign_state(OWNER, "github", secret=SECRET, now=1_000_000)
    assert verify_state(state, secret=SECRET, now=1_000_000 + STATE_TTL_SECONDS - 1)[0] == OWNER


def test_garbage_is_refused_rather_than_crashing() -> None:
    with pytest.raises(UnauthenticatedError, match="malformed"):
        verify_state("not-a-state", secret=SECRET)


def test_the_authorize_url_carries_the_scopes_and_state() -> None:
    url = authorize_url(
        "github",
        jira_oauth_base=JIRA_BASE,
        client_id="client-123",
        redirect_uri="https://app.test/callback",
        state="the-state",
    )
    assert url.startswith("https://github.com/login/oauth/authorize?")
    assert "client_id=client-123" in url
    assert "state=the-state" in url
    assert "read%3Auser" in url


def test_jira_asks_for_offline_access_so_the_weekly_sync_keeps_working() -> None:
    url = authorize_url(
        "jira",
        jira_oauth_base=JIRA_BASE,
        client_id="c",
        redirect_uri="https://app.test/cb",
        state="s",
    )
    assert "offline_access" in url
    assert "audience=api.atlassian.com" in url


def test_an_unknown_connector_is_refused() -> None:
    with pytest.raises(ValidationError, match="unknown connector"):
        authorize_url(
            "linkedin", jira_oauth_base=JIRA_BASE, client_id="c", redirect_uri="r", state="s"
        )


def test_jira_uses_the_configured_oauth_host_not_a_literal() -> None:
    """JIRA_OAUTH_BASE_URL used to be declared and silently ignored."""
    endpoints = endpoints_for("jira", jira_oauth_base="https://auth.example.test/")
    assert endpoints.authorize_url == "https://auth.example.test/authorize"
    assert endpoints.token_url == "https://auth.example.test/oauth/token"


def test_the_authorize_url_carries_the_redirect_the_provider_must_return_to() -> None:
    """The redirect is the SPA's page, which forwards code and state to the API."""
    url = authorize_url(
        "jira",
        jira_oauth_base=JIRA_BASE,
        client_id="c",
        redirect_uri="http://localhost:5173/connections/jira/callback",
        state="s",
    )
    assert "redirect_uri=http%3A%2F%2Flocalhost%3A5173%2Fconnections%2Fjira%2Fcallback" in url


def test_github_offers_its_account_picker_so_a_reconnect_can_switch_accounts() -> None:
    url = authorize_url(
        "github", jira_oauth_base=JIRA_BASE, client_id="c", redirect_uri="r", state="s"
    )
    assert "prompt=select_account" in url


def test_jira_asks_for_consent_so_a_reconnect_can_switch_accounts() -> None:
    url = authorize_url(
        "jira", jira_oauth_base=JIRA_BASE, client_id="c", redirect_uri="r", state="s"
    )
    assert "prompt=consent" in url


# --- token grants and refreshing ------------------------------------------------

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)


def test_a_grant_with_a_lifetime_expires_that_many_seconds_from_now() -> None:
    grant = parse_token_grant(
        "jira",
        {
            "access_token": "a",
            "refresh_token": "r",
            "expires_in": 3600,
            "scope": "read:jira-work offline_access",
        },
        now=NOW,
    )
    assert grant.expires_at == NOW + timedelta(hours=1)
    assert grant.refresh_token == "r"
    assert grant.scopes == ("read:jira-work", "offline_access")


def test_a_grant_without_a_lifetime_has_no_known_expiry() -> None:
    grant = parse_token_grant("github", {"access_token": "a", "scope": "repo"}, now=NOW)
    assert grant.expires_at is None
    assert grant.refresh_token is None


def test_a_grant_without_an_access_token_is_refused() -> None:
    with pytest.raises(UpstreamFailedError, match="no access token"):
        parse_token_grant("jira", {"refresh_token": "r"}, now=NOW)


class FakeTokenEndpoint:
    """Answers ``request`` with one canned response and keeps what was sent."""

    def __init__(self, status: int, body: Any) -> None:
        self.status = status
        self.body = body
        self.sent: list[dict[str, Any]] = []

    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        self.sent.append({"method": method, "url": url, **kwargs})
        return httpx.Response(self.status, json=self.body)


def _refresher() -> OAuthTokenRefresher:
    return OAuthTokenRefresher(
        "jira", jira_oauth_base=JIRA_BASE, client_id="client", client_secret="secret"
    )


async def test_a_refresh_trades_the_refresh_token_for_a_rotated_pair() -> None:
    endpoint = FakeTokenEndpoint(
        200, {"access_token": "new-a", "refresh_token": "new-r", "expires_in": 3600}
    )

    grant = await _refresher().refresh(endpoint, "old-r", now=NOW)  # type: ignore[arg-type]

    assert (grant.access_token, grant.refresh_token) == ("new-a", "new-r")
    assert grant.expires_at == NOW + timedelta(hours=1)
    (sent,) = endpoint.sent
    assert sent["url"] == f"{JIRA_BASE}/oauth/token"
    assert sent["json"] == {
        "grant_type": "refresh_token",
        "client_id": "client",
        "client_secret": "secret",
        "refresh_token": "old-r",
    }


@pytest.mark.parametrize("status", [400, 401, 403])
async def test_a_refused_refresh_asks_the_user_to_reconnect(status: int) -> None:
    endpoint = FakeTokenEndpoint(status, {"error": "invalid_grant"})
    with pytest.raises(UpstreamFailedError, match="Reconnect Jira"):
        await _refresher().refresh(endpoint, "spent", now=NOW)  # type: ignore[arg-type]


async def test_a_provider_outage_during_a_refresh_is_an_upstream_failure() -> None:
    endpoint = FakeTokenEndpoint(503, {})
    with pytest.raises(UpstreamFailedError, match="did not refresh"):
        await _refresher().refresh(endpoint, "r", now=NOW)  # type: ignore[arg-type]
