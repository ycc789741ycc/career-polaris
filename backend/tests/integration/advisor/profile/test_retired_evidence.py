"""A sync retiring a connector's old fact shapes, against a real database.

The unit tests prove the rule; this proves the delete reaches Postgres under
row-level security, takes only the retired shapes from the caller's source, and
leaves another owner's facts alone.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

import pytest

from advisor.profile import EvidenceSource, ProfileService, create_profile_service
from advisor.profile.infra.connectors import Connector, EvidenceDraft
from kernel.config import Settings
from kernel.db import Database
from kernel.storage import ObjectStore

pytestmark = pytest.mark.integration


def _draft(ref: str) -> EvidenceDraft:
    return EvidenceDraft(
        external_ref=ref,
        reference=f"GitHub · {ref}",
        fact=f"Work behind {ref}",
        observed_on=date(2026, 9, 1),
    )


class FakeGitHub(Connector):
    kind = "github"

    def __init__(self) -> None:
        self.refs = ["github:pr:1", "github:merged:acme/ledger", "github:reviews"]
        self.retired_refs: tuple[str, ...] = ()
        self.replaced_refs: tuple[str, ...] = ()

    async def account_name(self, client: Any, token: str) -> str:
        return token

    async def fetch(self, client: Any, token: str) -> list[EvidenceDraft]:
        return [_draft(ref) for ref in self.refs]


@pytest.fixture
def github() -> FakeGitHub:
    return FakeGitHub()


@pytest.fixture
def profile(database: Database, settings: Settings, github: FakeGitHub) -> ProfileService:
    return create_profile_service(
        database,
        object_store=ObjectStore(settings),
        connectors={"github": github},
        token_refreshers={},
        resume_max_bytes=settings.resume_max_bytes,
        resume_max_pages=settings.resume_max_pages,
        http_timeout_seconds=5,
        user_agent="test",
    )


async def _connect_and_sync(profile: ProfileService, owner: uuid.UUID, who: str) -> None:
    await profile.store_connection(
        owner, kind="github", access_token=who, refresh_token=None, scopes=(), expires_at=None
    )
    await profile.sync_connection(owner, "github")


async def test_a_sync_deletes_only_the_callers_retired_shapes(
    profile: ProfileService, github: FakeGitHub, account: uuid.UUID, other_account: uuid.UUID
) -> None:
    await _connect_and_sync(profile, account, "ada")
    await _connect_and_sync(profile, other_account, "grace")
    before = await profile.snapshot(account)

    github.refs = ["github:commits:acme/ledger", "github:reviews"]
    github.retired_refs = ("github:merged:*", "github:pr:*")
    await profile.sync_connection(account, "github")

    after = await profile.snapshot(account)
    assert sorted(e.reference for e in after.evidence) == [
        "GitHub · github:commits:acme/ledger",
        "GitHub · github:reviews",
    ]
    assert after.version == before.version + 1

    theirs = await profile.snapshot(other_account)
    assert sorted(e.reference for e in theirs.evidence if e.source is EvidenceSource.GITHUB) == [
        "GitHub · github:merged:acme/ledger",
        "GitHub · github:pr:1",
        "GitHub · github:reviews",
    ]
