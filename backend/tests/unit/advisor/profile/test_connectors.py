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


class SearchClient(FakeClient):
    """Also answers GitHub's searches, one page of ``items`` per call, and records each query."""

    def __init__(self, responses: dict[str, Any], pages: dict[str, list[list[Any]]]) -> None:
        super().__init__(responses)
        self.pages = pages
        self.queries: list[tuple[str, dict[str, Any]]] = []

    async def get_json(self, url: str, **kwargs: Any) -> Any:
        if url not in self.pages:
            return await super().get_json(url, **kwargs)
        params = kwargs["params"]
        self.queries.append((url, params))
        batches = self.pages[url]
        page = params["page"]
        return {"items": batches[page - 1] if page <= len(batches) else []}


COMMITS = f"{API}/search/commits"
ISSUES = f"{API}/search/issues"


def _commit(sha: str, repo: str = "acme/ledger", *, message: str = "Split the ledger") -> Any:
    return {
        "sha": sha,
        "repository": {"full_name": repo},
        "commit": {"message": message, "author": {"date": "2026-05-12T10:00:00Z"}},
    }


def _github(commits: list[list[Any]], reviewed: list[list[Any]] | None = None) -> SearchClient:
    return SearchClient(
        {f"{API}/user": {"login": "octo"}},
        {COMMITS: commits, ISSUES: reviewed or []},
    )


async def test_github_counts_commits_so_work_pushed_without_a_pull_request_counts() -> None:
    client = _github(
        [[_commit("a" * 40), _commit("b" * 40), _commit("c" * 40, "acme/docs")]],
        reviewed=[[{"id": 1, "repository_url": f"{API}/repos/acme/ledger"}]],
    )
    drafts = await GitHubConnector(API).fetch(client, "t")  # type: ignore[arg-type]

    shapes = {d.external_ref: (d.granularity, d.tally, d.subject) for d in drafts}
    assert shapes == {
        "github:commits:acme/ledger": (EvidenceGranularity.SUMMARY, 2, "acme/ledger"),
        "github:commits:acme/docs": (EvidenceGranularity.SUMMARY, 1, "acme/docs"),
        "github:reviews": (EvidenceGranularity.SUMMARY, 1, None),
        f"github:commit:{'a' * 40}": (EvidenceGranularity.ITEM, None, "acme/ledger"),
        f"github:commit:{'b' * 40}": (EvidenceGranularity.ITEM, None, "acme/ledger"),
        f"github:commit:{'c' * 40}": (EvidenceGranularity.ITEM, None, "acme/docs"),
    }
    tally = next(d for d in drafts if d.external_ref == "github:commits:acme/ledger")
    assert tally.fact == "2 commits authored in acme/ledger."


async def test_a_commit_is_cited_by_repository_and_short_sha_and_says_its_first_line() -> None:
    client = _github([[_commit("0123456789abcdef", message="Fix rounding\n\nLong story.")]])
    drafts = await GitHubConnector(API).fetch(client, "t")  # type: ignore[arg-type]

    (item,) = [d for d in drafts if d.external_ref.startswith("github:commit:")]
    assert (item.reference, item.fact, item.observed_on) == (
        "GitHub · acme/ledger@0123456",
        "Fix rounding",
        date(2026, 5, 12),
    )


async def test_github_searches_the_users_own_commits_without_merges_newest_first() -> None:
    client = _github([[_commit("a" * 40)]])
    await GitHubConnector(API).fetch(client, "t")  # type: ignore[arg-type]

    (commits,) = [params for url, params in client.queries if url == COMMITS]
    assert commits["q"] == "author:octo merge:false"
    assert (commits["sort"], commits["order"]) == ("author-date", "desc")


async def test_github_pages_through_commits_until_a_short_page() -> None:
    full = [_commit(f"{n:040x}") for n in range(100)]
    client = _github([full, [_commit("f" * 40)]])
    drafts = await GitHubConnector(API).fetch(client, "t")  # type: ignore[arg-type]

    assert [p["page"] for url, p in client.queries if url == COMMITS] == [1, 2]
    tally = next(d for d in drafts if d.external_ref == "github:commits:acme/ledger")
    assert tally.tally == 101
    assert sum(d.external_ref.startswith("github:commit:") for d in drafts) == 25


async def test_github_retires_the_pull_request_shapes_it_used_to_write() -> None:
    assert GitHubConnector(API).retired_refs == ("github:merged:", "github:pr:")
    assert JiraConnector(API).retired_refs == ()


async def test_a_jira_issue_without_a_key_names_no_project() -> None:
    keyless = {"id": "9", "fields": {"summary": "Orphan", "status": {"name": "Done"}}}
    client = FakeClient({SITES: [SITE], SEARCH: {"issues": [keyless]}})
    drafts = await JiraConnector(API).fetch(client, "t")  # type: ignore[arg-type]

    assert [d.subject for d in drafts if d.external_ref == "jira:issue:9"] == [None]
    assert not any(":project:" in d.external_ref for d in drafts)
