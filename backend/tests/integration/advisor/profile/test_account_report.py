"""Atlassian's personal data report against a real database, under row-level
security (ADR 0061).

The report reads two owners' connections — the user's, and the app owner's
whose token sends it — each in its own owner-scoped transaction. This proves
that works under RLS, that the accountId reaches Postgres, and that a closed
account's data really leaves it, while the app owner's stays.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date
from typing import Any

import pytest

from advisor.profile import (
    EvidenceSource,
    ProfileService,
    ReportAction,
    create_profile_service,
)
from advisor.profile.domain import AccountReportReply, ReportedAccount, ReportedStatus
from advisor.profile.infra.account_report import AccountReporter
from advisor.profile.infra.connectors import Connector, EvidenceDraft
from kernel.config import Settings
from kernel.db import Database
from kernel.storage import ObjectStore

pytestmark = pytest.mark.integration


class FakeJira(Connector):
    """Each token stands for its own Atlassian account."""

    kind = "jira"
    retired_refs: tuple[str, ...] = ()
    replaced_refs: tuple[str, ...] = ()

    async def account_name(self, client: Any, token: str) -> str:
        return f"{token} · acme"

    async def account_id(self, client: Any, token: str) -> str | None:
        return f"atl-{token}"

    async def fetch(self, client: Any, token: str) -> list[EvidenceDraft]:
        return [
            EvidenceDraft(
                external_ref=f"jira:issue:{token}",
                reference=f"Jira · {token}",
                fact=f"Closed {token}'s ticket",
                observed_on=date(2026, 9, 1),
            )
        ]


class ClosingReporter(AccountReporter):
    """Says the user's account was closed; keeps what it was sent."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, list[ReportedAccount]]] = []

    async def report(
        self, client: Any, access_token: str, accounts: Sequence[ReportedAccount]
    ) -> AccountReportReply:
        self.sent.append((access_token, list(accounts)))
        return AccountReportReply(statuses={"atl-ada": ReportedStatus.CLOSED})


def _profile(
    database: Database, settings: Settings, reporter: ClosingReporter, app_owner: uuid.UUID
) -> ProfileService:
    return create_profile_service(
        database,
        object_store=ObjectStore(settings),
        connectors={"jira": FakeJira()},
        token_refreshers={},
        resume_max_bytes=settings.resume_max_bytes,
        resume_max_pages=settings.resume_max_pages,
        http_timeout_seconds=5,
        user_agent="test",
        account_reporter=reporter,
        reporting_owner_id=app_owner,
    )


async def _connect_and_sync(profile: ProfileService, owner: uuid.UUID, token: str) -> None:
    await profile.store_connection(
        owner, kind="jira", access_token=token, refresh_token=None, scopes=(), expires_at=None
    )
    await profile.sync_connection(owner, "jira")


async def test_a_closed_account_is_erased_and_the_app_owners_data_stays(
    database: Database, settings: Settings, account: uuid.UUID, other_account: uuid.UUID
) -> None:
    app_owner, user = other_account, account
    reporter = ClosingReporter()
    profile = _profile(database, settings, reporter, app_owner)
    await _connect_and_sync(profile, app_owner, "owner")
    await _connect_and_sync(profile, user, "ada")

    decision = await profile.report_jira_account(user)

    ((token, (reported,)),) = reporter.sent
    assert token == "owner"
    assert reported.account_id == "atl-ada"
    assert decision.action is ReportAction.DISCONNECT
    assert decision.next_report_in_seconds is None

    assert await profile.connections(user) == []
    gone = await profile.snapshot(user)
    assert [e for e in gone.evidence if e.source is EvidenceSource.JIRA] == []

    kept = await profile.snapshot(app_owner)
    assert len([e for e in kept.evidence if e.source is EvidenceSource.JIRA]) == 1
    assert [c.account for c in await profile.connections(app_owner)] == ["owner · acme"]
