"""Jira: cycle time, epic ownership and incident response.

This is the scope evidence a resume usually loses — "shipped the thing" with
no way to show how big the thing was. Work is grouped by epic, because an epic
is the thing that was shipped; a project is only where a team files its tickets.

Only finished tickets count: one done, or handed over as "To be verified". A
ticket still open says what someone meant to do, not what they did.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import Any

from advisor.profile.domain import EvidenceGranularity
from advisor.profile.infra.connectors.base import Connector, EvidenceDraft
from kernel.errors import UpstreamFailedError
from kernel.fetch import GuardedClient
from kernel.parsing import parse_date

SCOPES = ("read:jira-work", "read:jira-user", "offline_access")
SCOPE_DESCRIPTIONS = (
    "Read issues and epics you are assigned to",
    "Read sprint and board history",
    "Read your Atlassian profile",
)

_PAGE_SIZE = 100
_MAX_ISSUES = 1000
_FIELDS = "summary,status,resolutiondate,updated,issuetype,parent"
# Jira's hierarchy: an epic is 1, a story or task 0, a subtask -1.
_EPIC_LEVEL = 1
# Only a key of this shape is ever written into a JQL query.
_ISSUE_KEY = re.compile(r"^[A-Z][A-Z0-9_]*-[0-9]+$")
_SUBJECT_LIMIT = 255
# A finished ticket: one of these status names, or any status in Jira's Done
# category (Done, Closed, Resolved — whatever the workflow calls it).
_VERIFYING = "to be verified"
_FINISHED_NAMES = frozenset({"done", _VERIFYING})
_DONE_CATEGORY = "done"


@dataclass(frozen=True, slots=True)
class Epic:
    key: str
    summary: str

    @property
    def label(self) -> str:
        """How the epic is named on a chart: its key, then what it is called."""
        return f"{self.key} {self.summary}".strip()[:_SUBJECT_LIMIT]


class JiraConnector(Connector):
    kind = "jira"
    # Tallies per project, which epics replaced.
    retired_refs: tuple[str, ...] = ("jira:*:project:*",)
    # Issues and epics a sync no longer returns — reopened, or never finished
    # when an earlier version wrote them — stop being evidence.
    replaced_refs: tuple[str, ...] = ("jira:issue:*", "jira:*:epic:*")

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
            # Filtered here rather than in JQL: a status name a site does not
            # have makes Jira refuse the whole query.
            issues = [
                i
                for i in await self._search(
                    client,
                    access_token,
                    str(cloud_id),
                    "assignee = currentUser() ORDER BY updated DESC",
                    _MAX_ISSUES,
                )
                if _is_finished(i.get("fields") or {})
            ]
            if not issues:
                continue
            epics = await self._epics(client, access_token, str(cloud_id), issues)

            verifying = sum(_status_name(i.get("fields") or {}) == _VERIFYING for i in issues)
            done = len(issues) - verifying
            drafts.append(
                EvidenceDraft(
                    external_ref=f"jira:{cloud_id}:throughput",
                    reference=f"Jira · {site_name}",
                    fact=f"{len(issues)} finished issues: {done} done, {verifying} to be verified.",
                    observed_on=_latest(_date_of(i) for i in issues),
                    granularity=EvidenceGranularity.SUMMARY,
                    tally=len(issues),
                )
            )

            by_epic = Counter(e for e in (epics.get(str(i.get("key"))) for i in issues) if e)
            worked = {
                epic: _latest(_date_of(i) for i in issues if epics.get(str(i.get("key"))) == epic)
                for epic in by_epic
            }
            # The ten epics worked on most recently, newest first; the busier on a tie.
            recent = sorted(
                by_epic, key=lambda e: (worked[e] or date.min, by_epic[e]), reverse=True
            )[:10]
            for epic in recent:
                count = by_epic[epic]
                drafts.append(
                    EvidenceDraft(
                        external_ref=f"jira:{cloud_id}:epic:{epic.key}",
                        reference=f"Jira · {site_name} · {epic.key}",
                        fact=f"{count} issues worked in the epic {epic.key}: {epic.summary}.",
                        observed_on=worked[epic],
                        granularity=EvidenceGranularity.SUMMARY,
                        tally=count,
                        subject=epic.label,
                    )
                )

            for issue in issues[:25]:
                fields = issue.get("fields") or {}
                summary = str(fields.get("summary") or "").strip()
                if not summary:
                    continue
                home = epics.get(str(issue.get("key")))
                drafts.append(
                    EvidenceDraft(
                        external_ref=f"jira:issue:{issue.get('id')}",
                        reference=f"Jira · {issue.get('key')}",
                        fact=summary,
                        observed_on=_date_of(issue),
                        subject=home.label if home else None,
                    )
                )
        return drafts

    async def _epics(
        self, client: GuardedClient, token: str, cloud_id: str, issues: list[dict[str, Any]]
    ) -> dict[str, Epic]:
        """The epic each issue belongs to, by issue key; an issue under none is left out.

        An epic assigned to the user counts as work in itself, and a story's
        epic is its parent. A subtask's parent is a story, so its epic is one
        level further up: those stories are read in one more search.
        """
        found: dict[str, Epic] = {}
        via_story: dict[str, list[str]] = {}
        for issue in issues:
            key = str(issue.get("key") or "")
            if not key:
                continue
            fields = issue.get("fields") or {}
            parent = fields.get("parent") if isinstance(fields.get("parent"), dict) else None
            if _is_epic(fields):
                found[key] = _epic_of(key, fields)
            elif parent is not None and _is_epic(parent.get("fields") or {}):
                found[key] = _epic_of(str(parent.get("key") or ""), parent.get("fields") or {})
            elif parent is not None and _ISSUE_KEY.match(str(parent.get("key") or "")):
                via_story.setdefault(str(parent["key"]), []).append(key)

        stories = list(via_story)
        for start in range(0, len(stories), _PAGE_SIZE):
            chunk = stories[start : start + _PAGE_SIZE]
            for story in await self._search(
                client, token, cloud_id, f"key in ({','.join(chunk)})", len(chunk)
            ):
                parent = (story.get("fields") or {}).get("parent")
                if not isinstance(parent, dict) or not _is_epic(parent.get("fields") or {}):
                    continue
                epic = _epic_of(str(parent.get("key") or ""), parent.get("fields") or {})
                for subtask in via_story.get(str(story.get("key")), []):
                    found[subtask] = epic
        # One epic per key, however many issues named it: the first summary seen wins.
        canonical: dict[str, Epic] = {}
        for epic in found.values():
            canonical.setdefault(epic.key, epic)
        return {key: canonical[epic.key] for key, epic in found.items() if epic.key}

    async def _search(
        self, client: GuardedClient, token: str, cloud_id: str, jql: str, limit: int
    ) -> list[dict[str, Any]]:
        """Page through a search by ``nextPageToken`` until the last page or ``limit``."""
        found: list[dict[str, Any]] = []
        page_token: str | None = None
        while len(found) < limit:
            params: dict[str, Any] = {"jql": jql, "maxResults": _PAGE_SIZE, "fields": _FIELDS}
            if page_token:
                params["nextPageToken"] = page_token
            payload = await client.get_json(
                f"{self._base}/ex/jira/{cloud_id}/rest/api/3/search/jql",
                headers=_headers(token),
                params=params,
            )
            if not isinstance(payload, dict):
                break
            batch = list(payload.get("issues") or [])
            found.extend(batch)
            page_token = payload.get("nextPageToken")
            if not batch or payload.get("isLast", True) or not page_token:
                break
        return found[:limit]


def _headers(token: str) -> dict[str, str]:
    return {"authorization": f"Bearer {token}", "accept": "application/json"}


def _is_epic(fields: dict[str, Any]) -> bool:
    """By hierarchy level where Jira sends it, by the type's name where it does not."""
    kind = fields.get("issuetype")
    if not isinstance(kind, dict):
        return False
    level = kind.get("hierarchyLevel")
    if isinstance(level, int):
        return level == _EPIC_LEVEL
    return str(kind.get("name") or "").lower() == "epic"


def _status_name(fields: dict[str, Any]) -> str:
    status = fields.get("status")
    return str(status.get("name") or "").strip().lower() if isinstance(status, dict) else ""


def _is_finished(fields: dict[str, Any]) -> bool:
    """Done, or waiting to be verified: work that was actually carried out."""
    if _status_name(fields) in _FINISHED_NAMES:
        return True
    status = fields.get("status")
    category = status.get("statusCategory") if isinstance(status, dict) else None
    return isinstance(category, dict) and category.get("key") == _DONE_CATEGORY


def _epic_of(key: str, fields: dict[str, Any]) -> Epic:
    return Epic(key=key, summary=str(fields.get("summary") or "").strip())


def _date_of(issue: dict[str, Any]) -> date | None:
    """When the work happened: resolved, or last touched while still open."""
    fields = issue.get("fields") or {}
    return parse_date(fields.get("resolutiondate") or fields.get("updated"))


def _latest(dates: Iterable[date | None]) -> date | None:
    known = [d for d in dates if d is not None]
    return max(known) if known else None
