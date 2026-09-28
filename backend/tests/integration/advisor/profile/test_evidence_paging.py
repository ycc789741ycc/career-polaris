"""Paging the evidence list against a real database, under row-level security.

The unit tests prove the page arithmetic; this proves the store's page and its
count agree in one transaction, and that another owner's facts are in neither.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

import pytest

from advisor.profile import ProfileService, create_profile_service
from advisor.profile.infra.connectors import EvidenceDraft
from kernel.config import Settings
from kernel.db import Database
from kernel.storage import ObjectStore

pytestmark = pytest.mark.integration

FACTS = 5


class FakeJira:
    kind = "jira"
    retired_refs: tuple[str, ...] = ()
    replaced_refs: tuple[str, ...] = ()

    async def account_name(self, client: Any, token: str) -> str:
        return token

    async def fetch(self, client: Any, token: str) -> list[EvidenceDraft]:
        return [
            EvidenceDraft(
                external_ref=f"jira:issue:{n}",
                reference=f"Jira · ACME-{n}",
                fact=f"Closed ACME-{n}",
                observed_on=date(2026, 9, 1),
            )
            for n in range(FACTS)
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


async def _sync(profile: ProfileService, owner: uuid.UUID) -> None:
    await profile.store_connection(
        owner, kind="jira", access_token="t", refresh_token=None, scopes=(), expires_at=None
    )
    await profile.sync_connection(owner, "jira")


async def test_pages_of_evidence_cover_the_list_once_and_count_only_the_callers(
    profile: ProfileService, account: uuid.UUID, other_account: uuid.UUID
) -> None:
    await _sync(profile, account)
    await _sync(profile, other_account)

    whole = await profile.evidence(account)
    mine = await profile.snapshot(account)
    assert whole.total == len(whole.items) == len(mine.evidence) > 2

    page_count = -(-whole.total // 2)
    pages = [await profile.evidence(account, page=n, page_size=2) for n in range(1, page_count + 1)]

    assert {p.total for p in pages} == {whole.total}
    assert all(len(p.items) == 2 for p in pages[:-1]) and 1 <= len(pages[-1].items) <= 2
    # Every fact exactly once, in the same order as the whole list.
    assert [e.id for p in pages for e in p.items] == [e.id for e in whole.items]
    assert (whole.page, whole.page_size) == (1, None)
