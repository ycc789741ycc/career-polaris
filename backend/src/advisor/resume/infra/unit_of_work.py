"""The Resume Advisor's unit of work over SQL: one owner-zone transaction per scope.

The scope opens ``Database.for_user`` — exactly the session the use cases used
to open themselves — so row-level security applies as before. Events recorded in
it go to the outbox in the same transaction, just before it commits.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, assert_never

from sqlalchemy.ext.asyncio import AsyncSession

from advisor.resume.domain import (
    OwnerResumes,
    ResumeEvent,
    ResumeTailored,
    ResumeUnitOfWork,
    ResumeVersionSaved,
)
from advisor.resume.infra.repositories import (
    SqlAlchemyExportRepository,
    SqlAlchemyResumeVersionRepository,
    SqlAlchemyRevisionRepository,
    SqlAlchemyTailoredResumeRepository,
)
from kernel.db import Database
from kernel.outbox import EventName, emit


class SqlAlchemyOwnerResumes(OwnerResumes):
    def __init__(self, session: AsyncSession, owner_id: uuid.UUID) -> None:
        self.resumes = SqlAlchemyTailoredResumeRepository(session, owner_id=owner_id)
        self.versions = SqlAlchemyResumeVersionRepository(session, owner_id=owner_id)
        self.revisions = SqlAlchemyRevisionRepository(session, owner_id=owner_id)
        self.exports = SqlAlchemyExportRepository(session, owner_id=owner_id)
        self.pending: list[ResumeEvent] = []

    def record(self, event: ResumeEvent) -> None:
        self.pending.append(event)


class SqlAlchemyResumeUnitOfWork(ResumeUnitOfWork):
    def __init__(self, database: Database) -> None:
        self._db = database

    @asynccontextmanager
    async def for_owner(self, owner_id: uuid.UUID) -> AsyncIterator[SqlAlchemyOwnerResumes]:
        async with self._db.for_user(owner_id) as session:
            scope = SqlAlchemyOwnerResumes(session, owner_id)
            yield scope
            for event in scope.pending:
                name, payload, owner = _outbox_entry(event)
                await emit(session, name, payload, owner_id=owner)


def _outbox_entry(event: ResumeEvent) -> tuple[EventName, dict[str, Any], uuid.UUID]:
    """The outbox name, payload and routing owner for each résumé event.

    These payloads are a contract with the dispatcher and must not drift.
    """
    match event:
        case ResumeTailored():
            return (
                EventName.RESUME_TAILORED,
                {"resume_id": str(event.resume_id), "role_id": str(event.role_id)},
                event.owner_id,
            )
        case ResumeVersionSaved():
            return (
                EventName.RESUME_VERSION_SAVED,
                {
                    "resume_id": str(event.resume_id),
                    "number": event.number,
                    "source": str(event.source),
                },
                event.owner_id,
            )
        case _:
            assert_never(event)
