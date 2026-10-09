"""A résumé line is dated by the upload it was last found in (ADR 0037), read
against a real database under row-level security."""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy import text

from advisor.profile import EvidenceSource, ProfileService, create_profile_service
from kernel.config import Settings
from kernel.db import Database
from kernel.storage import ObjectStore

pytestmark = pytest.mark.integration

RESUME = b"Jane Doe\n- Led the migration of the billing platform to event sourcing\n"


@pytest.fixture
def profile(database: Database, settings: Settings) -> ProfileService:
    return create_profile_service(
        database,
        object_store=ObjectStore(settings),
        connectors={},
        token_refreshers={},
        resume_max_bytes=settings.resume_max_bytes,
        resume_max_pages=settings.resume_max_pages,
        http_timeout_seconds=5,
        user_agent="test",
    )


async def _upload(
    profile: ProfileService, database: Database, owner: uuid.UUID, on: date, name: str
) -> uuid.UUID:
    uploaded = await profile.upload_resume(
        owner, filename=name, content_type="text/plain", content=RESUME
    )
    async with database.for_user(owner) as session:
        await session.execute(
            text("UPDATE profile.resume_file SET created_at = :on WHERE id = :id"),
            {"on": on, "id": uploaded.id},
        )
    await profile.parse_resume(owner, uploaded.id)
    return uploaded.id


async def test_a_resume_line_takes_the_date_of_the_newest_upload_that_states_it(
    profile: ProfileService, database: Database, account: uuid.UUID, other_account: uuid.UUID
) -> None:
    await _upload(profile, database, account, date(2025, 5, 2), "cv.txt")
    first = (await profile.snapshot(account)).evidence
    assert {e.stated_on for e in first} == {date(2025, 5, 2)}

    await _upload(profile, database, account, date(2026, 9, 30), "cv.txt")
    after = (await profile.snapshot(account)).evidence

    assert {e.source for e in after} == {EvidenceSource.RESUME}
    assert {e.stated_on for e in after} == {date(2026, 9, 30)}
    assert (await profile.snapshot(other_account)).evidence == ()
