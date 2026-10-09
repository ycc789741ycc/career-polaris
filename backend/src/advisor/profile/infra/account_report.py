"""Atlassian's personal data reporting API, for OAuth 2.0 (3LO) apps (ADR 0061).

``POST {JIRA_API_BASE_URL}/app/report-accounts/`` takes up to 90 accounts,
each an ``accountId`` and when we last fetched its data. It answers 204 when
nothing needs doing, or 200 listing the accounts that were closed or updated.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

from advisor.profile.domain import (
    AccountReportReply,
    ReportedAccount,
    ReportedStatus,
    parse_cycle_period,
    parse_reported_status,
)
from kernel.errors import UpstreamFailedError
from kernel.fetch import GuardedClient


class AccountReporter(Protocol):
    """Sends one report, with the app owner's access token."""

    async def report(
        self, client: GuardedClient, access_token: str, accounts: Sequence[ReportedAccount]
    ) -> AccountReportReply: ...


class AtlassianAccountReporter(AccountReporter):
    def __init__(self, api_base_url: str) -> None:
        self._url = f"{api_base_url.rstrip('/')}/app/report-accounts/"

    async def report(
        self, client: GuardedClient, access_token: str, accounts: Sequence[ReportedAccount]
    ) -> AccountReportReply:
        response = await client.request(
            "POST",
            self._url,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            json={
                "accounts": [
                    {"accountId": a.account_id, "updatedAt": _rfc3339(a)} for a in accounts
                ]
            },
        )
        cycle = parse_cycle_period(response.headers.get("Cycle-Period"))
        status = response.status_code
        if status == 204:
            return AccountReportReply(cycle_period_seconds=cycle)
        if status == 429:
            retry_after = parse_cycle_period(response.headers.get("Retry-After"))
            return AccountReportReply(retry_after_seconds=retry_after or 60)
        if status == 400:
            raise UpstreamFailedError(
                "Atlassian refused the personal data report as malformed",
                status=status,
                detail=response.text[:500],
            )
        if status != 200:
            raise UpstreamFailedError(
                f"Atlassian's personal data report failed with {status}", status=status
            )
        return AccountReportReply(statuses=_statuses(response), cycle_period_seconds=cycle)


def _rfc3339(account: ReportedAccount) -> str:
    return account.updated_at.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _statuses(response: Any) -> dict[str, ReportedStatus]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise UpstreamFailedError("Atlassian's report reply was not JSON") from exc
    found: dict[str, ReportedStatus] = {}
    for row in (payload or {}).get("accounts", []) if isinstance(payload, dict) else []:
        if not isinstance(row, dict):
            continue
        status = parse_reported_status(row.get("status"))
        account_id = row.get("accountId")
        if status is not None and isinstance(account_id, str):
            found[account_id] = status
    return found
