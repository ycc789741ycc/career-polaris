"""Fill the gap's unit of work over SQL: one owner-zone transaction per scope.

The scope opens ``Database.for_user``, so row-level security applies. Events
recorded in it go to the outbox in the same transaction, just before it
commits.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession

from advisor.gapfill.domain import GapFillEvent
from advisor.gapfill.infra.repositories import (
    SqlAlchemyGapQuestionRepository,
    SqlAlchemyQuestionSetRepository,
)
from kernel.db import Database
from kernel.outbox import EventName, emit


class SqlAlchemyOwnerGapFill:
    def __init__(self, session: AsyncSession, owner_id: uuid.UUID) -> None:
        self.sets = SqlAlchemyQuestionSetRepository(session, owner_id=owner_id)
        self.questions = SqlAlchemyGapQuestionRepository(session, owner_id=owner_id)
        self.pending: list[GapFillEvent] = []

    def record(self, event: GapFillEvent) -> None:
        self.pending.append(event)


class SqlAlchemyGapFillUnitOfWork:
    def __init__(self, database: Database) -> None:
        self._db = database

    @asynccontextmanager
    async def for_owner(self, owner_id: uuid.UUID) -> AsyncIterator[SqlAlchemyOwnerGapFill]:
        async with self._db.for_user(owner_id) as session:
            scope = SqlAlchemyOwnerGapFill(session, owner_id)
            yield scope
            for event in scope.pending:
                # The payload is a contract with the dispatcher and must not drift.
                await emit(
                    session,
                    EventName.GAP_ANSWERS_SUBMITTED,
                    {
                        "set_id": str(event.set_id),
                        "role_id": str(event.role_id),
                        "job_posting_id": (
                            str(event.job_posting_id) if event.job_posting_id else None
                        ),
                        "evidence_ids": list(event.evidence_ids),
                    },
                    owner_id=event.owner_id,
                )
