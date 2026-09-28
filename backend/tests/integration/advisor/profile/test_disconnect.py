"""Disconnecting a source against a real database, under row-level security.

The unit tests prove the rule; this proves the delete reaches Postgres, takes
only the caller's facts from that source, and leaves another owner's alone.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

import pytest

from advisor.profile import EvidenceSource, ProfileService, create_profile_service
from advisor.profile.infra.connectors import EvidenceDraft
from kernel.config import Settings
from kernel.db import Database
from kernel.storage import ObjectStore

pytestmark = pytest.mark.integration


class FakeJira:
    kind = "jira"
    retired_refs: tuple[str, ...] = ()
    replaced_refs: tuple[str, ...] = ()

    async def account_name(self, client: Any, token: str) -> str:
        return f"{token} · acme"

    async def fetch(self, client: Any, token: str) -> list[EvidenceDraft]:
        return [
            EvidenceDraft(
                external_ref=f"jira:issue:{n}",
                reference=f"Jira · ACME-{n}",
                fact=f"Closed ACME-{n}",
                observed_on=date(2026, 9, 1),
            )
            for n in range(3)
        ]


@pytest.fixture
def profile(database: Database, settings: Settings) -> ProfileService:
    return create_profile_service(
        database,
        object_store=ObjectStore(settings),
        connectors={"jira": FakeJira()},
        resume_max_bytes=settings.resume_max_bytes,
        resume_max_pages=settings.resume_max_pages,
        http_timeout_seconds=5,
        user_agent="test",
    )


async def _connect_and_sync(profile: ProfileService, owner: uuid.UUID, who: str) -> None:
    await profile.store_connection(
        owner, kind="jira", access_token=who, refresh_token=None, scopes=(), expires_at=None
    )
    await profile.sync_connection(owner, "jira")


async def test_disconnect_removes_only_the_callers_facts_from_that_source(
    profile: ProfileService, account: uuid.UUID, other_account: uuid.UUID
) -> None:
    await _connect_and_sync(profile, account, "ada")
    await _connect_and_sync(profile, other_account, "grace")
    await profile.record_answer(account, question_id="q1", question="Who led it?", answer="I did")
    (connected,) = await profile.connections(account)
    assert connected.account == "ada · acme"
    before = await profile.snapshot(account)

    await profile.disconnect(account, "jira")

    after = await profile.snapshot(account)
    assert await profile.connections(account) == []
    assert {e.source for e in after.evidence} == {EvidenceSource.SELF_REPORTED}
    assert after.version == before.version + 1

    theirs = await profile.snapshot(other_account)
    assert len([e for e in theirs.evidence if e.source is EvidenceSource.JIRA]) == 3
    assert [c.account for c in await profile.connections(other_account)] == ["grace · acme"]
