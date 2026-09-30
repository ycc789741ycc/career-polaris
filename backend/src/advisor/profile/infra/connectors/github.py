"""GitHub: the commits someone authored, and the pull requests they reviewed.

Work is counted by commit, not by pull request, so work pushed straight to a
branch counts as much as work that went through review. A squash-merged pull
request still counts: its commit on the default branch carries its author.

Read-only scopes. Everything fetched is treated as untrusted text — repository
names and commit messages end up in prompts as data, never as instructions.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from datetime import date
from typing import Any

from advisor.profile.domain import EvidenceGranularity
from advisor.profile.infra.connectors.base import Connector, EvidenceDraft
from kernel.errors import UpstreamFailedError
from kernel.fetch import GuardedClient
from kernel.parsing import parse_date

SCOPES = ("read:user", "repo:status", "public_repo")
SCOPE_DESCRIPTIONS = (
    "Read repository metadata and commit history",
    "Read the pull requests you reviewed",
    "Read your public profile",
)

# GitHub's search answers at most 1000 results, 100 to a page.
_PAGE_SIZE = 100
_MAX_COMMITS = 1000
_MAX_REVIEWS = 100


class GitHubConnector(Connector):
    kind = "github"
    # Shapes the pull-request version of this connector wrote. A sync deletes
    # them, so the same work never counts once as merged pull requests and
    # again as commits.
    retired_refs: tuple[str, ...] = ("github:merged:*", "github:pr:*")
    replaced_refs: tuple[str, ...] = ()

    def __init__(self, api_base_url: str) -> None:
        self._base = api_base_url.rstrip("/")

    async def account_name(self, client: GuardedClient, access_token: str) -> str:
        user = await self._get(client, access_token, "/user")
        login = user.get("login") if isinstance(user, dict) else None
        if not login:
            raise UpstreamFailedError("GitHub did not return an account")
        return str(login)

    async def fetch(self, client: GuardedClient, access_token: str) -> list[EvidenceDraft]:
        login = await self.account_name(client, access_token)

        drafts: list[EvidenceDraft] = []
        commits = await self._commits(client, access_token, login)
        reviewed = await self._search(
            client, access_token, "/search/issues", f"is:pr reviewed-by:{login}", _MAX_REVIEWS
        )

        by_repo = Counter(_repo_of_commit(c) for c in commits)
        for repo, count in by_repo.most_common(10):
            if not repo:
                continue
            drafts.append(
                EvidenceDraft(
                    external_ref=f"github:commits:{repo}",
                    reference=f"GitHub · {repo}",
                    fact=f"{count} commits authored in {repo}.",
                    observed_on=_latest(
                        _commit_date(c) for c in commits if _repo_of_commit(c) == repo
                    ),
                    granularity=EvidenceGranularity.SUMMARY,
                    tally=count,
                    subject=repo,
                )
            )

        if reviewed:
            drafts.append(
                EvidenceDraft(
                    external_ref="github:reviews",
                    reference="GitHub reviews",
                    fact=(
                        f"{len(reviewed)} pull requests reviewed across "
                        f"{len({_repo_of_issue(i) for i in reviewed})} repositories."
                    ),
                    observed_on=_latest(_issue_date(i) for i in reviewed),
                    granularity=EvidenceGranularity.SUMMARY,
                    tally=len(reviewed),
                )
            )

        for commit in commits[:25]:
            sha = str(commit.get("sha") or "")
            headline = _headline(commit)
            repo = _repo_of_commit(commit)
            if not sha or not headline or not repo:
                continue
            drafts.append(
                EvidenceDraft(
                    external_ref=f"github:commit:{sha}",
                    reference=f"GitHub · {repo}@{sha[:7]}",
                    fact=headline,
                    observed_on=_commit_date(commit),
                    subject=repo,
                )
            )
        return drafts

    async def _commits(self, client: GuardedClient, token: str, login: str) -> list[dict[str, Any]]:
        """Newest first. Merge commits are left out: they join work, they are not work."""
        return await self._search(
            client,
            token,
            "/search/commits",
            f"author:{login} merge:false",
            _MAX_COMMITS,
            sort="author-date",
        )

    async def _get(self, client: GuardedClient, token: str, path: str) -> Any:
        return await client.get_json(f"{self._base}{path}", headers=_headers(token))

    async def _search(
        self,
        client: GuardedClient,
        token: str,
        path: str,
        query: str,
        limit: int,
        *,
        sort: str = "updated",
    ) -> list[dict[str, Any]]:
        """Page through a search until it runs out or reaches ``limit``."""
        found: list[dict[str, Any]] = []
        page = 1
        while len(found) < limit:
            payload = await client.get_json(
                f"{self._base}{path}",
                headers=_headers(token),
                params={
                    "q": query,
                    "sort": sort,
                    "order": "desc",
                    "per_page": _PAGE_SIZE,
                    "page": page,
                },
            )
            items = payload.get("items") if isinstance(payload, dict) else None
            batch = list(items or [])
            found.extend(batch)
            if len(batch) < _PAGE_SIZE:
                break
            page += 1
        return found[:limit]


def _headers(token: str) -> dict[str, str]:
    return {
        "authorization": f"Bearer {token}",
        "accept": "application/vnd.github+json",
        "x-github-api-version": "2022-11-28",
    }


def _repo_of_commit(commit: dict[str, Any]) -> str | None:
    repository = commit.get("repository")
    name = repository.get("full_name") if isinstance(repository, dict) else None
    return str(name) if name else None


def _headline(commit: dict[str, Any]) -> str:
    """The first line of the message: what the commit says it does."""
    detail = commit.get("commit")
    message = detail.get("message") if isinstance(detail, dict) else None
    return str(message or "").strip().split("\n", 1)[0].strip()


def _commit_date(commit: dict[str, Any]) -> date | None:
    """When it was written, which a rebase or a cherry-pick leaves alone."""
    detail = commit.get("commit")
    author = detail.get("author") if isinstance(detail, dict) else None
    return parse_date(author.get("date")) if isinstance(author, dict) else None


def _repo_of_issue(item: dict[str, Any]) -> str | None:
    url = str(item.get("repository_url") or "")
    return url.rsplit("/repos/", 1)[-1] if "/repos/" in url else None


def _issue_date(item: dict[str, Any]) -> date | None:
    return parse_date(item.get("closed_at") or item.get("updated_at"))


def _latest(dates: Iterable[date | None]) -> date | None:
    known = [d for d in dates if d is not None]
    return max(known) if known else None
