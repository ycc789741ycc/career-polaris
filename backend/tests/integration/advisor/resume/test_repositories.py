"""The SQLAlchemy side of the Resume Advisor's repositories, against a real
database.

Worth proving here: a résumé's Target and options survive their mappers, the
latest-number aggregate is per résumé and per owner, and each event lands in
the outbox as the dispatcher reads it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text

from advisor.resume.domain import (
    Options,
    ResumeTailored,
    ResumeVersion,
    ResumeVersionFilter,
    ResumeVersionSaved,
    TailoredResume,
    TailoredResumeFilter,
    Template,
    VersionSource,
)
from advisor.resume.infra.unit_of_work import SqlAlchemyResumeUnitOfWork
from kernel.db import Database

pytestmark = pytest.mark.integration

AT = datetime(2026, 9, 27, tzinfo=UTC)


def _resume(owner_id: uuid.UUID) -> TailoredResume:
    return TailoredResume.requested(
        owner_id=owner_id,
        target_kind="privatePosting",
        target_id=uuid.uuid4(),
        label="Staff Engineer at Acme",
        template=Template.PLAIN,
        options=Options(metrics=False, reorder=True, trim=True),
        at=AT,
    )


def _version(resume: TailoredResume, number: int) -> ResumeVersion:
    return ResumeVersion(
        id=uuid.uuid4(),
        owner_id=resume.owner_id,
        resume_id=resume.id,
        number=number,
        label=f"v{number}",
        content={"name": "Maya"},
        source=VersionSource.MANUAL,
        created_at=AT,
    )


async def test_resumes_round_trip_and_latest_numbers_are_per_resume(
    database: Database, account: uuid.UUID, other_account: uuid.UUID
) -> None:
    uow = SqlAlchemyResumeUnitOfWork(database)
    async with uow.for_owner(account) as mine:
        first = await mine.resumes.create(_resume(account))
        second = await mine.resumes.create(_resume(account))
        for number in (1, 2, 3):
            await mine.versions.create(_version(first, number))
        await mine.versions.create(_version(second, 1))
    async with uow.for_owner(other_account) as theirs:
        elsewhere = await theirs.resumes.create(_resume(other_account))
        await theirs.versions.create(_version(elsewhere, 7))

    async with uow.for_owner(account) as mine:
        assert await mine.resumes.get(first.id) == first
        assert await mine.resumes.get_count(TailoredResumeFilter()) == 2
        assert await mine.versions.latest_numbers() == {first.id: 3, second.id: 1}
        [two] = await mine.versions.get_list(ResumeVersionFilter(resume_id=first.id, number=2))
        assert two.label == "v2"
    async with database.for_user(account) as session:
        stored = await session.execute(
            text("SELECT private_posting_id, options FROM resume.resume WHERE id = :id"),
            {"id": first.id},
        )
        target, options = stored.one()
    assert target == first.target_id
    assert options == {"metrics": False, "reorder": True, "trim": True}


async def test_resume_events_reach_the_outbox_as_the_dispatcher_reads_them(
    database: Database, account: uuid.UUID
) -> None:
    uow = SqlAlchemyResumeUnitOfWork(database)
    resume_id = uuid.uuid4()
    async with uow.for_owner(account) as mine:
        mine.record(
            ResumeTailored(owner_id=account, resume_id=resume_id, target_kind="matchedPosting")
        )
        mine.record(
            ResumeVersionSaved(
                owner_id=account, resume_id=resume_id, number=2, source=VersionSource.CHAT
            )
        )

    async with database.shared() as session:
        rows = await session.execute(
            text("SELECT name, payload FROM outbox.event WHERE owner_id = :owner"),
            {"owner": account},
        )
        assert sorted(tuple(r) for r in rows.all()) == [
            ("ResumeTailored", {"resume_id": str(resume_id), "target_kind": "matchedPosting"}),
            ("ResumeVersionSaved", {"resume_id": str(resume_id), "number": 2, "source": "chat"}),
        ]
