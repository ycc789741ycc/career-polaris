"""Connectors name the account a token belongs to, or refuse to."""

from __future__ import annotations

from typing import Any

import pytest

from advisor.profile.infra.connectors import GitHubConnector, JiraConnector
from kernel.errors import UpstreamFailedError

API = "https://api.example.test"


class FakeClient:
    """Answers ``get_json`` from a table of URL -> payload; no network."""

    def __init__(self, responses: dict[str, Any]) -> None:
        self.responses = responses

    async def get_json(self, url: str, **_: Any) -> Any:
        return self.responses[url]


SITE = {"id": "cloud-1", "name": "acme"}
SITES = f"{API}/oauth/token/accessible-resources"
MYSELF = f"{API}/ex/jira/cloud-1/rest/api/3/myself"


async def test_jira_names_the_person_their_email_and_the_site() -> None:
    client = FakeClient(
        {SITES: [SITE], MYSELF: {"displayName": "Ada Lovelace", "emailAddress": "ada@acme.io"}}
    )
    name = await JiraConnector(API).account_name(client, "t")  # type: ignore[arg-type]
    assert name == "Ada Lovelace (ada@acme.io) · acme"


async def test_jira_leaves_out_an_email_the_user_keeps_private() -> None:
    client = FakeClient({SITES: [SITE], MYSELF: {"displayName": "Ada Lovelace"}})
    name = await JiraConnector(API).account_name(client, "t")  # type: ignore[arg-type]
    assert name == "Ada Lovelace · acme"


async def test_jira_without_an_accessible_site_is_refused() -> None:
    client = FakeClient({SITES: []})
    with pytest.raises(UpstreamFailedError, match="any site"):
        await JiraConnector(API).account_name(client, "t")  # type: ignore[arg-type]


async def test_jira_without_a_user_is_refused() -> None:
    client = FakeClient({SITES: [SITE], MYSELF: {}})
    with pytest.raises(UpstreamFailedError, match="account"):
        await JiraConnector(API).account_name(client, "t")  # type: ignore[arg-type]


async def test_github_names_the_login() -> None:
    client = FakeClient({f"{API}/user": {"login": "octo"}})
    assert await GitHubConnector(API).account_name(client, "t") == "octo"  # type: ignore[arg-type]


async def test_github_without_a_login_is_refused() -> None:
    client = FakeClient({f"{API}/user": {}})
    with pytest.raises(UpstreamFailedError):
        await GitHubConnector(API).account_name(client, "t")  # type: ignore[arg-type]
