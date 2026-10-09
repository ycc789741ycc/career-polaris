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


async def test_jira_keeps_the_atlassian_account_id_for_the_data_report() -> None:
    client = FakeClient({SITES: [SITE], MYSELF: {"displayName": "Ada", "accountId": "5b10ac8d"}})
    assert await JiraConnector(API).account_id(client, "t") == "5b10ac8d"  # type: ignore[arg-type]


async def test_jira_without_an_account_id_is_refused() -> None:
    client = FakeClient({SITES: [SITE], MYSELF: {"displayName": "Ada"}})
    with pytest.raises(UpstreamFailedError, match="account id"):
        await JiraConnector(API).account_id(client, "t")  # type: ignore[arg-type]


async def test_github_keeps_no_account_id() -> None:
    assert await GitHubConnector(API).account_id(FakeClient({}), "t") is None  # type: ignore[arg-type]


async def test_github_names_the_login() -> None:
    client = FakeClient({f"{API}/user": {"login": "octo"}})
    assert await GitHubConnector(API).account_name(client, "t") == "octo"  # type: ignore[arg-type]


async def test_github_without_a_login_is_refused() -> None:
    client = FakeClient({f"{API}/user": {}})
    with pytest.raises(UpstreamFailedError):
        await GitHubConnector(API).account_name(client, "t")  # type: ignore[arg-type]


# --- what a sync gathers ---------------------------------------------------

SEARCH = f"{API}/ex/jira/cloud-1/rest/api/3/search/jql"


DONE = {"name": "Done", "statusCategory": {"key": "done"}}
VERIFYING = {"name": "To be verified", "statusCategory": {"key": "indeterminate"}}
IN_PROGRESS = {"name": "In Progress", "statusCategory": {"key": "indeterminate"}}
TO_DO = {"name": "To Do", "statusCategory": {"key": "new"}}


def _issue(
    key: str, *, resolved: str | None = None, updated: str | None = None, status: Any = None
) -> Any:
    return {
        "id": key,
        "key": key,
        "fields": {
            "summary": f"Work on {key}",
            "status": status or (DONE if resolved else VERIFYING),
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


class JqlClient(FakeClient):
    """Answers Jira's search by its JQL, one page per ``nextPageToken``; records each query."""

    def __init__(self, pages: dict[str, list[list[Any]]]) -> None:
        super().__init__({SITES: [SITE]})
        self.pages = pages
        self.queries: list[dict[str, Any]] = []

    async def get_json(self, url: str, **kwargs: Any) -> Any:
        if url != SEARCH:
            return await super().get_json(url, **kwargs)
        params = kwargs["params"]
        self.queries.append(params)
        batches = self.pages.get(params["jql"], [])
        page = int(params.get("nextPageToken") or 0)
        is_last = page + 1 >= len(batches)
        return {
            "issues": batches[page] if page < len(batches) else [],
            "isLast": is_last,
            **({} if is_last else {"nextPageToken": str(page + 1)}),
        }


MINE = "assignee = currentUser() ORDER BY updated DESC"
EPIC_TYPE = {"name": "Epic", "hierarchyLevel": 1}
STORY_TYPE = {"name": "Story", "hierarchyLevel": 0}
SUBTASK_TYPE = {"name": "Subtask", "hierarchyLevel": -1}
LEDGER = {"key": "PAY-1", "fields": {"summary": "Ledger rewrite", "issuetype": EPIC_TYPE}}


def _work(key: str, *, kind: Any = STORY_TYPE, parent: Any = None) -> Any:
    issue = _issue(key, resolved="2026-05-12")
    issue["fields"]["issuetype"] = kind
    if parent is not None:
        issue["fields"]["parent"] = parent
    return issue


async def test_jira_tallies_issues_by_their_epic_and_every_fact_names_it() -> None:
    """A story counts toward its parent epic, and an epic you own toward itself.

    The owned epic's own summary differs from the copy its stories carry, as a
    rename between reads would leave it: it is still one epic.
    """
    client = JqlClient(
        {
            MINE: [
                [
                    _work("PAY-2", parent=LEDGER),
                    _work("OPS-9", parent=LEDGER),
                    _work("PAY-1", kind=EPIC_TYPE),
                    _work("PAY-3"),
                ]
            ]
        }
    )
    drafts = await JiraConnector(API).fetch(client, "t")  # type: ignore[arg-type]

    shapes = {d.external_ref: (d.granularity, d.tally, d.subject) for d in drafts}
    assert shapes == {
        "jira:cloud-1:throughput": (EvidenceGranularity.SUMMARY, 4, None),
        "jira:cloud-1:epic:PAY-1": (EvidenceGranularity.SUMMARY, 3, "PAY-1 Ledger rewrite"),
        "jira:issue:PAY-2": (EvidenceGranularity.ITEM, None, "PAY-1 Ledger rewrite"),
        "jira:issue:OPS-9": (EvidenceGranularity.ITEM, None, "PAY-1 Ledger rewrite"),
        "jira:issue:PAY-1": (EvidenceGranularity.ITEM, None, "PAY-1 Ledger rewrite"),
        "jira:issue:PAY-3": (EvidenceGranularity.ITEM, None, None),
    }
    tally = next(d for d in drafts if d.external_ref == "jira:cloud-1:epic:PAY-1")
    assert (tally.reference, tally.fact) == (
        "Jira · acme · PAY-1",
        "3 issues worked in the epic PAY-1: Ledger rewrite.",
    )


def _under(epic: str, n: int, *, resolved: str) -> Any:
    parent = {"key": epic, "fields": {"summary": epic, "issuetype": EPIC_TYPE}}
    issue = _work(f"W-{epic}-{n}", parent=parent)
    issue["fields"]["resolutiondate"] = resolved
    return issue


async def test_jira_keeps_the_ten_epics_worked_on_most_recently_newest_first() -> None:
    """A busy epic from last year gives way to a small one from this month."""
    old_and_busy = [_under("OLD-1", n, resolved="2025-01-10") for n in range(30)]
    recent = [_under(f"NEW-{m}", 0, resolved=f"2026-09-{m:02d}") for m in range(1, 11)]
    client = JqlClient({MINE: [old_and_busy + recent]})
    drafts = await JiraConnector(API).fetch(client, "t")  # type: ignore[arg-type]

    epics = [d.external_ref for d in drafts if ":epic:" in d.external_ref]
    assert epics == [f"jira:cloud-1:epic:NEW-{m}" for m in range(10, 0, -1)]


async def test_a_subtask_counts_toward_the_epic_of_its_story() -> None:
    story = {"key": "PAY-2", "fields": {"summary": "Story", "issuetype": STORY_TYPE}}
    client = JqlClient(
        {
            MINE: [[_work("PAY-5", kind=SUBTASK_TYPE, parent=story)]],
            "key in (PAY-2)": [[_work("PAY-2", parent=LEDGER)]],
        }
    )
    drafts = await JiraConnector(API).fetch(client, "t")  # type: ignore[arg-type]

    assert [d.subject for d in drafts if d.external_ref == "jira:issue:PAY-5"] == [
        "PAY-1 Ledger rewrite"
    ]


async def test_a_parent_key_that_is_not_a_jira_key_never_reaches_a_query() -> None:
    odd = {"key": "PAY-2) OR (project = X", "fields": {"issuetype": STORY_TYPE}}
    client = JqlClient({MINE: [[_work("PAY-5", kind=SUBTASK_TYPE, parent=odd)]]})
    drafts = await JiraConnector(API).fetch(client, "t")  # type: ignore[arg-type]

    assert [q["jql"] for q in client.queries] == [MINE]
    assert not any(":epic:" in d.external_ref for d in drafts)


async def test_jira_pages_through_the_users_issues() -> None:
    client = JqlClient({MINE: [[_work(f"PAY-{n}") for n in range(100)], [_work("PAY-100")]]})
    drafts = await JiraConnector(API).fetch(client, "t")  # type: ignore[arg-type]

    assert [q.get("nextPageToken") for q in client.queries] == [None, "1"]
    throughput = next(d for d in drafts if d.external_ref == "jira:cloud-1:throughput")
    assert throughput.tally == 101


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
    assert GitHubConnector(API).retired_refs == ("github:merged:*", "github:pr:*")


async def test_a_jira_issue_without_a_key_names_no_epic() -> None:
    keyless = {"id": "9", "fields": {"summary": "Orphan", "status": {"name": "Done"}}}
    client = FakeClient({SITES: [SITE], SEARCH: {"issues": [keyless]}})
    drafts = await JiraConnector(API).fetch(client, "t")  # type: ignore[arg-type]

    assert [d.subject for d in drafts if d.external_ref == "jira:issue:9"] == [None]
    assert not any(":epic:" in d.external_ref for d in drafts)


async def test_jira_retires_the_project_tallies_epics_replaced() -> None:
    assert JiraConnector(API).retired_refs == ("jira:*:project:*",)


async def test_jira_replaces_its_issues_and_epics_on_every_sync() -> None:
    assert JiraConnector(API).replaced_refs == ("jira:issue:*", "jira:*:epic:*")


def _with(key: str, status: Any) -> Any:
    return _issue(key, updated="2026-06-03", status=status)


async def test_only_done_or_to_be_verified_tickets_are_evidence() -> None:
    closed = {"name": "Closed", "statusCategory": {"key": "done"}}
    shouting = {"name": "TO BE VERIFIED", "statusCategory": {"key": "indeterminate"}}
    client = JqlClient(
        {
            MINE: [
                [
                    _with("PAY-1", DONE),
                    _with("PAY-2", VERIFYING),
                    _with("PAY-3", closed),
                    _with("PAY-4", shouting),
                    _with("PAY-5", IN_PROGRESS),
                    _with("PAY-6", TO_DO),
                ]
            ]
        }
    )
    drafts = await JiraConnector(API).fetch(client, "t")  # type: ignore[arg-type]

    items = sorted(d.reference for d in drafts if d.external_ref.startswith("jira:issue:"))
    assert items == ["Jira · PAY-1", "Jira · PAY-2", "Jira · PAY-3", "Jira · PAY-4"]
    throughput = next(d for d in drafts if d.external_ref == "jira:cloud-1:throughput")
    assert (throughput.tally, throughput.fact) == (
        4,
        "4 finished issues: 2 done, 2 to be verified.",
    )


async def test_an_unfinished_epic_is_no_work_of_its_own_but_still_names_its_stories() -> None:
    open_epic = _work("PAY-1", kind=EPIC_TYPE)
    open_epic["fields"]["status"] = IN_PROGRESS
    client = JqlClient({MINE: [[open_epic, _work("PAY-2", parent=LEDGER)]]})
    drafts = await JiraConnector(API).fetch(client, "t")  # type: ignore[arg-type]

    shapes = {d.external_ref: (d.tally, d.subject) for d in drafts}
    assert shapes == {
        "jira:cloud-1:throughput": (1, None),
        "jira:cloud-1:epic:PAY-1": (1, "PAY-1 Ledger rewrite"),
        "jira:issue:PAY-2": (None, "PAY-1 Ledger rewrite"),
    }


async def test_a_site_with_nothing_finished_gives_no_evidence() -> None:
    client = JqlClient({MINE: [[_with("PAY-1", IN_PROGRESS), _with("PAY-2", TO_DO)]]})
    assert await JiraConnector(API).fetch(client, "t") == []  # type: ignore[arg-type]
