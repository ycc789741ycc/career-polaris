"""Deleting a résumé against a real database and object store, under row-level security.

The unit tests prove the rule; this proves the file leaves object storage, the
delete reaches Postgres, and another owner's résumé is untouched.
"""

from __future__ import annotations

import uuid

import pytest
from botocore.exceptions import ClientError

from advisor.profile import EvidenceSource, ProfileService, create_profile_service
from kernel.config import Settings
from kernel.db import Database
from kernel.errors import NotFoundError
from kernel.storage import ObjectStore, object_key

pytestmark = pytest.mark.integration

RESUME = (
    b"Jane Doe\n"
    b"- Led the migration of the billing platform to event sourcing\n"
    b"- Cut p99 checkout latency from 900ms to 180ms across three regions\n"
)


@pytest.fixture
def store(settings: Settings) -> ObjectStore:
    return ObjectStore(settings)


@pytest.fixture
def profile(database: Database, settings: Settings, store: ObjectStore) -> ProfileService:
    return create_profile_service(
        database,
        object_store=store,
        connectors={},
        resume_max_bytes=settings.resume_max_bytes,
        resume_max_pages=settings.resume_max_pages,
        http_timeout_seconds=5,
        user_agent="test",
    )


async def _upload_and_parse(profile: ProfileService, owner: uuid.UUID) -> uuid.UUID:
    uploaded = await profile.upload_resume(
        owner, filename="cv.txt", content_type="text/plain", content=RESUME
    )
    await profile.parse_resume(owner, uploaded.id)
    return uploaded.id


async def test_deleting_a_resume_removes_its_file_and_facts_and_nobody_elses(
    profile: ProfileService, account: uuid.UUID, other_account: uuid.UUID
) -> None:
    mine = await _upload_and_parse(profile, account)
    theirs = await _upload_and_parse(profile, other_account)
    await profile.record_answer(account, question_id="q1", question="Who led it?", answer="I did")
    before = await profile.snapshot(account)

    await profile.delete_resume(account, mine)

    after = await profile.snapshot(account)
    assert {e.source for e in after.evidence} == {EvidenceSource.USER_ANSWER}
    assert after.version == before.version + 1
    assert (await profile.resumes(account)).items == ()
    with pytest.raises(NotFoundError):
        await profile.resume_download_url(account, mine)

    theirs_after = await profile.snapshot(other_account)
    assert any(e.source is EvidenceSource.RESUME for e in theirs_after.evidence)
    assert [r.id for r in (await profile.resumes(other_account)).items] == [theirs]

    with pytest.raises(NotFoundError):
        await profile.delete_resume(account, theirs)


async def test_the_deleted_file_is_gone_from_object_storage(
    profile: ProfileService, store: ObjectStore, account: uuid.UUID
) -> None:
    resume_id = await _upload_and_parse(profile, account)
    assert await profile.base_resume_text(account) is not None

    await profile.delete_resume(account, resume_id)

    assert await profile.base_resume_text(account) is None
    with pytest.raises(ClientError):
        store.get(object_key(account, "resumes", str(resume_id)))


async def test_a_line_a_newer_upload_restates_survives_deleting_the_older(
    profile: ProfileService, account: uuid.UUID
) -> None:
    """The newer upload takes the line over in the database, not only in memory."""
    older = await _upload_and_parse(profile, account)
    newer = await _upload_and_parse(profile, account)
    count = len((await profile.snapshot(account)).evidence)

    await profile.delete_resume(account, older)
    assert len((await profile.snapshot(account)).evidence) == count

    await profile.delete_resume(account, newer)
    assert (await profile.snapshot(account)).evidence == ()
