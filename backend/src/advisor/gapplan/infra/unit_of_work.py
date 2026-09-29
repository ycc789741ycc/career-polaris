"""The gap plan's unit of work over SQL: one owner-zone transaction per scope.

The scope opens ``Database.for_user`` — exactly the session the use cases used
to open themselves — so row-level security applies as before. Events recorded in
it go to the outbox in the same transaction, just before it commits.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession

from advisor.gapplan.domain import GapPlanEvent
from advisor.gapplan.infra.repositories import (
    SqlAlchemyGapPlanRepository,
    SqlAlchemyMilestoneRepository,
    SqlAlchemyTaskRepository,
)
from kernel.db import Database
from kernel.outbox import EventName, emit


class SqlAlchemyOwnerGapPlans:
    def __init__(self, session: AsyncSession, owner_id: uuid.UUID) -> None:
        self.plans = SqlAlchemyGapPlanRepository(session, owner_id=owner_id)
        self.milestones = SqlAlchemyMilestoneRepository(session, owner_id=owner_id)
        self.tasks = SqlAlchemyTaskRepository(session, owner_id=owner_id)
        self.pending: list[GapPlanEvent] = []

    def record(self, event: GapPlanEvent) -> None:
        self.pending.append(event)


class SqlAlchemyGapPlanUnitOfWork:
    def __init__(self, database: Database) -> None:
        self._db = database

    @asynccontextmanager
    async def for_owner(self, owner_id: uuid.UUID) -> AsyncIterator[SqlAlchemyOwnerGapPlans]:
        async with self._db.for_user(owner_id) as session:
            scope = SqlAlchemyOwnerGapPlans(session, owner_id)
            yield scope
            for event in scope.pending:
                # The payload is a contract with the dispatcher and must not drift.
                await emit(
                    session,
                    EventName.PLAN_DRAFTED,
                    {
                        "plan_id": str(event.plan_id),
                        "role_id": str(event.role_id),
                        "version": event.version,
                    },
                    owner_id=event.owner_id,
                )
