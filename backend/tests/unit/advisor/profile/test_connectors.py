"""Connectors name the account a token belongs to, or refuse to."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from advisor.profile.domain import EvidenceGranularity
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


# --- what a sync gathers ---------------------------------------------------

SEARCH = f"{API}/ex/jira/cloud-1/rest/api/3/search/jql"


def _issue(key: str, *, resolved: str | None = None, updated: str | None = None) -> Any:
    return {
        "id": key,
        "key": key,
        "fields": {
            "summary": f"Work on {key}",
            "status": {"name": "Done" if resolved else "In Progress"},
            "resolutiondate": resolved,
            "updated": updated,
        },
    }


async def test_jira_dates_each_issue_when_it_was_resolved_or_last_touched() -> None:
    client = FakeClient(
        {
            SITES: [SITE],
            SEARCH: {
                "issues": [
                    _issue("PAY-1", resolved="2026-05-12T10:22:33.000+0000"),
                    _issue("PAY-2", updated="2026-06-03T08:00:00.000+0000"),
                ]
            },
        }
    )
    drafts = await JiraConnector(API).fetch(client, "t")  # type: ignore[arg-type]

    items = {d.reference: d.observed_on for d in drafts if d.external_ref.startswith("jira:issue:")}
    assert items == {"Jira · PAY-1": date(2026, 5, 12), "Jira · PAY-2": date(2026, 6, 3)}


async def test_jira_tallies_count_their_issues_and_every_fact_names_its_project() -> None:
    """Counting work over time must not count a tally as one more piece of work."""
    client = FakeClient(
        {SITES: [SITE], SEARCH: {"issues": [_issue("PAY-1", resolved="2026-05-12")]}}
    )
    drafts = await JiraConnector(API).fetch(client, "t")  # type: ignore[arg-type]

    shapes = {d.external_ref: (d.granularity, d.tally, d.subject) for d in drafts}
    assert shapes == {
        "jira:cloud-1:throughput": (EvidenceGranularity.SUMMARY, 1, None),
        "jira:cloud-1:project:PAY": (EvidenceGranularity.SUMMARY, 1, "PAY"),
        "jira:issue:PAY-1": (EvidenceGranularity.ITEM, None, "PAY"),
    }


async def test_github_tallies_count_their_prs_and_every_pr_names_its_repository() -> None:
    pr = {
        "id": 7,
        "number": 214,
        "title": "Split the ledger writer",
        "repository_url": f"{API}/repos/acme/ledger",
        "closed_at": "2026-05-12T10:00:00Z",
    }
    client = FakeClient(
        {
            f"{API}/user": {"login": "octo"},
            f"{API}/search/issues": {"items": [pr]},
        }
    )
    drafts = await GitHubConnector(API).fetch(client, "t")  # type: ignore[arg-type]

    shapes = {d.external_ref: (d.granularity, d.tally, d.subject) for d in drafts}
    assert shapes == {
        "github:merged:acme/ledger": (EvidenceGranularity.SUMMARY, 1, "acme/ledger"),
        "github:reviews": (EvidenceGranularity.SUMMARY, 1, None),
        "github:pr:7": (EvidenceGranularity.ITEM, None, "acme/ledger"),
    }


async def test_a_jira_issue_without_a_key_names_no_project() -> None:
    keyless = {"id": "9", "fields": {"summary": "Orphan", "status": {"name": "Done"}}}
    client = FakeClient({SITES: [SITE], SEARCH: {"issues": [keyless]}})
    drafts = await JiraConnector(API).fetch(client, "t")  # type: ignore[arg-type]

    assert [d.subject for d in drafts if d.external_ref == "jira:issue:9"] == [None]
    assert not any(":project:" in d.external_ref for d in drafts)
