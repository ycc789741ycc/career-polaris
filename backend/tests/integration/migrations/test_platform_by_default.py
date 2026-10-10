"""Migration 0053: an account that stored a key before the platform became the
default keeps running on it, and a choice already made is left alone
(ADR 0066). The backfill runs here as each owner, under the owner policy."""

from __future__ import annotations

import importlib
import uuid

import pytest
from sqlalchemy import text

from kernel.db import Database

pytestmark = pytest.mark.integration

BACKFILL = importlib.import_module(
    "migrations.versions.20261024_0053_platform_by_default"
).BACKFILL_OWN_CHOICES


async def _sources(database: Database, owner: uuid.UUID) -> list[str]:
    async with database.for_user(owner) as session:
        await session.execute(text(BACKFILL))
    async with database.for_user(owner) as session:
        return list(
            (await session.execute(text("SELECT source FROM identity.ai_source_choice")))
            .scalars()
            .all()
        )


async def test_a_key_holder_with_no_choice_keeps_their_own_key(
    database: Database, account: uuid.UUID
) -> None:
    async with database.for_user(account) as session:
        await session.execute(
            text(
                "INSERT INTO identity.provider_credential"
                " (id, owner_id, provider, model, encrypted_api_key, last_four, status)"
                " VALUES (:id, :owner, 'anthropic', 'claude-haiku-4-5', 'x', 'abcd', 'active')"
            ),
            {"id": uuid.uuid4(), "owner": account},
        )

    assert await _sources(database, account) == ["own"]
    # Run again, it adds nothing.
    assert await _sources(database, account) == ["own"]


async def test_a_choice_already_made_is_left_alone(
    database: Database, other_account: uuid.UUID
) -> None:
    async with database.for_user(other_account) as session:
        await session.execute(
            text(
                "INSERT INTO identity.provider_credential"
                " (id, owner_id, provider, model, encrypted_api_key, last_four, status)"
                " VALUES (:id, :owner, 'openai', 'gpt-5.1', 'x', 'abcd', 'active')"
            ),
            {"id": uuid.uuid4(), "owner": other_account},
        )
        await session.execute(
            text(
                "INSERT INTO identity.ai_source_choice (id, owner_id, source)"
                " VALUES (:id, :owner, 'platform')"
            ),
            {"id": uuid.uuid4(), "owner": other_account},
        )

    assert await _sources(database, other_account) == ["platform"]
