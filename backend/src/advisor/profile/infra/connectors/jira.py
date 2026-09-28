"""Jira: cycle time, epic ownership and incident response.

This is the scope evidence a resume usually loses — "shipped the thing" with
no way to show how big the thing was.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from datetime import date
from typing import Any

from advisor.profile.domain import EvidenceGranularity
from advisor.profile.infra.connectors.base import EvidenceDraft
from kernel.errors import UpstreamFailedError
from kernel.fetch import GuardedClient
from kernel.parsing import parse_date

SCOPES = ("read:jira-work", "read:jira-user", "offline_access")
SCOPE_DESCRIPTIONS = (
    "Read issues and epics you are assigned to",
    "Read sprint and board history",
    "Read your Atlassian profile",
)

_MAX_ISSUES = 100


class JiraConnector:
    kind = "jira"
    retired_refs: tuple[str, ...] = ()

    def __init__(self, api_base_url: str) -> None:
        self._base = api_base_url.rstrip("/")

    async def sites(self, client: GuardedClient, access_token: str) -> list[dict[str, Any]]:
        payload = await client.get_json(
            f"{self._base}/oauth/token/accessible-resources", headers=_headers(access_token)
        )
        return list(payload or [])

    async def account_name(self, client: GuardedClient, access_token: str) -> str:
        """The Atlassian user and the site they granted, e.g. "Ada (ada@x.io) · acme".

        The person comes from the first site's ``/myself``, which the
        ``read:jira-user`` scope already covers. The email is left out when the
        user's Atlassian privacy settings hide it.
        """
        sites = await self.sites(client, access_token)
        site = next((s for s in sites if s.get("id")), None)
        if site is None:
            raise UpstreamFailedError("Jira did not grant access to any site")
        me = await client.get_json(
            f"{self._base}/ex/jira/{site['id']}/rest/api/3/myself",
            headers=_headers(access_token),
        )
        name = me.get("displayName") if isinstance(me, dict) else None
        if not name:
            raise UpstreamFailedError("Jira did not return an account")
        email = me.get("emailAddress") if isinstance(me, dict) else None
        person = f"{name} ({email})" if email else str(name)
        return f"{person} · {site.get('name') or 'jira'}"

    async def fetch(self, client: GuardedClient, access_token: str) -> list[EvidenceDraft]:
        sites = await self.sites(client, access_token)
        drafts: list[EvidenceDraft] = []

        for site in sites[:3]:
            cloud_id = site.get("id")
            site_name = str(site.get("name") or "jira")
            if not cloud_id:
                continue
            issues = await self._search(client, access_token, str(cloud_id))
            if not issues:
                continue

            statuses = Counter(
                str(((i.get("fields") or {}).get("status") or {}).get("name") or "unknown")
                for i in issues
            )
            done = sum(count for name, count in statuses.items() if name.lower() == "done")
            drafts.append(
                EvidenceDraft(
                    external_ref=f"jira:{cloud_id}:throughput",
                    reference=f"Jira · {site_name}",
                    fact=f"{len(issues)} assigned issues, {done} of them closed.",
                    observed_on=_latest_date(issues),
                    confidence=0.85,
                    granularity=EvidenceGranularity.SUMMARY,
                    tally=len(issues),
                )
            )

            projects = Counter(p for p in (_project_of(i) for i in issues) if p)
            for project, count in projects.most_common(5):
                drafts.append(
                    EvidenceDraft(
                        external_ref=f"jira:{cloud_id}:project:{project}",
                        reference=f"Jira · {site_name} · {project}",
                        fact=f"{count} issues worked in the {project} project.",
                        observed_on=_latest_date(i for i in issues if _project_of(i) == project),
                        confidence=0.8,
                        granularity=EvidenceGranularity.SUMMARY,
                        tally=count,
                        subject=project,
                    )
                )

            for issue in issues[:25]:
                fields = issue.get("fields") or {}
                summary = str(fields.get("summary") or "").strip()
                if not summary:
                    continue
                drafts.append(
                    EvidenceDraft(
                        external_ref=f"jira:issue:{issue.get('id')}",
                        reference=f"Jira · {issue.get('key')}",
                        fact=summary,
                        observed_on=_date_of(issue),
                        confidence=0.75,
                        subject=_project_of(issue),
                    )
                )
        return drafts

    async def _search(
        self, client: GuardedClient, token: str, cloud_id: str
    ) -> list[dict[str, Any]]:
        payload = await client.get_json(
            f"{self._base}/ex/jira/{cloud_id}/rest/api/3/search/jql",
            headers=_headers(token),
            params={
                "jql": "assignee = currentUser() ORDER BY updated DESC",
                "maxResults": _MAX_ISSUES,
                "fields": "summary,status,resolutiondate,updated",
            },
        )
        issues = payload.get("issues") if isinstance(payload, dict) else None
        return list(issues or [])


def _headers(token: str) -> dict[str, str]:
    return {"authorization": f"Bearer {token}", "accept": "application/json"}


def _project_of(issue: dict[str, Any]) -> str | None:
    """The project key, "PAY" for "PAY-12"; None for an issue without a key."""
    key = issue.get("key")
    return str(key).split("-", 1)[0] if key else None


def _date_of(issue: dict[str, Any]) -> date | None:
    """When the work happened: resolved, or last touched while still open."""
    fields = issue.get("fields") or {}
    return parse_date(fields.get("resolutiondate") or fields.get("updated"))


def _latest_date(issues: Iterable[dict[str, Any]]) -> date | None:
    dates = [d for d in (_date_of(i) for i in issues) if d is not None]
    return max(dates) if dates else None
