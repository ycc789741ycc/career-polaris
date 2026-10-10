"""Migration 0051's checks: a credential is for one of the three providers we
call, and only an OpenAI key names its own endpoint (ADR 0065)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from kernel.db import Database

pytestmark = pytest.mark.integration

_INSERT = (
    "INSERT INTO identity.provider_credential"
    " (id, owner_id, provider, model, base_url, encrypted_api_key, last_four, status)"
    " VALUES (:id, :owner, :provider, 'm', :base_url, 'x', 'abcd', 'active')"
)


@pytest.mark.parametrize(
    ("provider", "base_url", "constraint"),
    [
        ("local", "https://llm.example.com/v1", "ck_provider_credential_provider"),
        ("anthropic", "https://proxy.example.com", "ck_provider_credential_base_url"),
    ],
    ids=["local", "base-url-off-openai"],
)
async def test_a_credential_we_cannot_call_is_refused(
    database: Database, account: uuid.UUID, provider: str, base_url: str, constraint: str
) -> None:
    with pytest.raises(IntegrityError, match=constraint):
        async with database.for_user(account) as session:
            await session.execute(
                text(_INSERT),
                {"id": uuid.uuid4(), "owner": account, "provider": provider, "base_url": base_url},
            )


async def test_an_openai_key_may_name_an_openai_compatible_cloud(
    database: Database, account: uuid.UUID
) -> None:
    credential_id = uuid.uuid4()
    async with database.for_user(account) as session:
        await session.execute(
            text(_INSERT),
            {
                "id": credential_id,
                "owner": account,
                "provider": "openai",
                "base_url": "https://api.groq.com/openai/v1",
            },
        )
    async with database.for_user(account) as session:
        await session.execute(
            text("DELETE FROM identity.provider_credential WHERE id = :id"), {"id": credential_id}
        )
