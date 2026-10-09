"""Connector OAuth.

Separate from login OAuth in every way: different provider, different tokens,
different scopes, different storage. The two never share a code path
(docs/architecture.md section 4).

State is an HMAC over the user, the connector and a timestamp, so the callback
can be verified without a server-side session table.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol
from urllib.parse import urlencode

from kernel.errors import UnauthenticatedError, UpstreamFailedError, ValidationError
from kernel.fetch import GuardedClient

STATE_TTL_SECONDS = 600


@dataclass(frozen=True, slots=True)
class ProviderEndpoints:
    authorize_url: str
    token_url: str
    scopes: tuple[str, ...]
    extra_authorize_params: dict[str, str]


GITHUB = ProviderEndpoints(
    authorize_url="https://github.com/login/oauth/authorize",
    token_url="https://github.com/login/oauth/access_token",  # noqa: S106 - a URL
    scopes=("read:user", "repo:status", "public_repo"),
    # Show GitHub's account picker rather than silently reusing whoever is
    # signed in to the browser, so reconnecting can switch accounts.
    extra_authorize_params={"prompt": "select_account"},
)


def jira_endpoints(oauth_base: str) -> ProviderEndpoints:
    """Atlassian's endpoints, rooted at the configured JIRA_OAUTH_BASE_URL.

    Built from configuration rather than a literal host, so the value in .env
    is the one actually used — pointing it at a test double works, and there is
    no second copy of the host to drift out of step.
    """
    base = oauth_base.rstrip("/")
    return ProviderEndpoints(
        authorize_url=f"{base}/authorize",
        token_url=f"{base}/oauth/token",
        scopes=("read:jira-work", "read:jira-user", "offline_access"),
        extra_authorize_params={"audience": "api.atlassian.com", "prompt": "consent"},
    )


def endpoints_for(kind: str, *, jira_oauth_base: str) -> ProviderEndpoints:
    if kind == "github":
        return GITHUB
    if kind == "jira":
        return jira_endpoints(jira_oauth_base)
    raise ValidationError(f"unknown connector {kind!r}", kind=kind)


def sign_state(owner_id: uuid.UUID, kind: str, *, secret: str, now: float | None = None) -> str:
    payload = json.dumps(
        {"o": str(owner_id), "k": kind, "t": int(now or time.time())},
        separators=(",", ":"),
    ).encode()
    signature = hmac.new(secret.encode(), payload, hashlib.sha256).digest()
    return f"{_b64(payload)}.{_b64(signature)}"


def verify_state(state: str, *, secret: str, now: float | None = None) -> tuple[uuid.UUID, str]:
    try:
        payload_b64, signature_b64 = state.split(".", 1)
        payload = _unb64(payload_b64)
        signature = _unb64(signature_b64)
    except (ValueError, TypeError) as exc:
        raise UnauthenticatedError("the OAuth state is malformed") from exc

    expected = hmac.new(secret.encode(), payload, hashlib.sha256).digest()
    if not hmac.compare_digest(signature, expected):
        raise UnauthenticatedError("the OAuth state does not verify")

    data = json.loads(payload)
    if (now or time.time()) - float(data["t"]) > STATE_TTL_SECONDS:
        raise UnauthenticatedError("this authorization attempt expired; start again")
    return uuid.UUID(data["o"]), str(data["k"])


def authorize_url(
    kind: str,
    *,
    jira_oauth_base: str,
    client_id: str,
    redirect_uri: str,
    state: str,
) -> str:
    endpoints = endpoints_for(kind, jira_oauth_base=jira_oauth_base)
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(endpoints.scopes),
        "state": state,
        **endpoints.extra_authorize_params,
    }
    return f"{endpoints.authorize_url}?{urlencode(params)}"


async def exchange_code(
    client: GuardedClient,
    kind: str,
    *,
    jira_oauth_base: str,
    code: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
) -> dict[str, Any]:
    endpoints = endpoints_for(kind, jira_oauth_base=jira_oauth_base)

    response = await client.request(
        "POST",
        endpoints.token_url,
        headers={"accept": "application/json", "content-type": "application/json"},
        json={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
        },
    )
    if response.status_code >= 400:
        raise UpstreamFailedError(
            f"{kind} rejected the authorization code", status=response.status_code
        )
    payload = response.json()
    if not isinstance(payload, dict) or "access_token" not in payload:
        raise UpstreamFailedError(f"{kind} returned no access token")
    return payload


@dataclass(frozen=True, slots=True)
class TokenGrant:
    """What a provider's token endpoint handed back, as the profile stores it."""

    access_token: str
    refresh_token: str | None
    scopes: tuple[str, ...]
    expires_at: datetime | None


def parse_token_grant(kind: str, payload: dict[str, Any], *, now: datetime) -> TokenGrant:
    """A token endpoint's reply. ``expires_in`` (seconds) becomes a time;
    without it (GitHub's OAuth apps) the token has no known expiry."""
    access_token = payload.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise UpstreamFailedError(f"{kind} returned no access token")
    refresh_token = payload.get("refresh_token")
    expires_in = payload.get("expires_in")
    return TokenGrant(
        access_token=access_token,
        refresh_token=refresh_token if isinstance(refresh_token, str) and refresh_token else None,
        scopes=tuple(str(payload.get("scope", "")).split()),
        expires_at=(
            now + timedelta(seconds=int(expires_in))
            if isinstance(expires_in, int | float) and expires_in > 0
            else None
        ),
    )


class TokenRefresher(Protocol):
    """Trades a connection's refresh token for a fresh grant."""

    async def refresh(
        self, client: GuardedClient, refresh_token: str, *, now: datetime
    ) -> TokenGrant: ...


class OAuthTokenRefresher(TokenRefresher):
    """The ``refresh_token`` grant against one provider's token endpoint."""

    def __init__(
        self, kind: str, *, jira_oauth_base: str, client_id: str, client_secret: str
    ) -> None:
        self._kind = kind
        self._token_url = endpoints_for(kind, jira_oauth_base=jira_oauth_base).token_url
        self._client_id = client_id
        self._client_secret = client_secret

    async def refresh(
        self, client: GuardedClient, refresh_token: str, *, now: datetime
    ) -> TokenGrant:
        response = await client.request(
            "POST",
            self._token_url,
            headers={"accept": "application/json", "content-type": "application/json"},
            json={
                "grant_type": "refresh_token",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "refresh_token": refresh_token,
            },
        )
        if response.status_code in (400, 401, 403):
            # Revoked, expired after months unused, or already rotated away:
            # only signing in again gets a new one.
            raise UpstreamFailedError(
                f"{self._kind.capitalize()} no longer accepts this connection. "
                f"Reconnect {self._kind.capitalize()} to keep syncing.",
                status=response.status_code,
            )
        if response.status_code >= 400:
            raise UpstreamFailedError(
                f"{self._kind} did not refresh the token", status=response.status_code
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise UpstreamFailedError(f"{self._kind} returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise UpstreamFailedError(f"{self._kind} returned no access token")
        return parse_token_grant(self._kind, payload, now=now)


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
