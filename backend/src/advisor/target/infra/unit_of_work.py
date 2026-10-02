"""Target's unit of work over SQL: one owner-zone transaction per scope.

The scope opens ``Database.for_user``, so row-level security applies. Target
records no events: a posting of the user's own builds nothing and tells no one.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession

from advisor.target.domain import OwnerTarget, TargetUnitOfWork
from advisor.target.infra.repositories import (
    SqlAlchemyOwnPostingFitRepository,
    SqlAlchemyPostingEvaluationRepository,
    SqlAlchemyPostingRequirementFitRepository,
    SqlAlchemyPostingRequirementRepository,
    SqlAlchemyPrivateJobPostingRepository,
)
from kernel.db import Database


class SqlAlchemyOwnerTarget(OwnerTarget):
    def __init__(self, session: AsyncSession, owner_id: uuid.UUID) -> None:
        self.postings = SqlAlchemyPrivateJobPostingRepository(session, owner_id=owner_id)
        self.evaluations = SqlAlchemyPostingEvaluationRepository(session, owner_id=owner_id)
        self.requirements = SqlAlchemyPostingRequirementRepository(session, owner_id=owner_id)
        self.requirement_fits = SqlAlchemyPostingRequirementFitRepository(
            session, owner_id=owner_id
        )
        self.fits = SqlAlchemyOwnPostingFitRepository(session, owner_id=owner_id)


class SqlAlchemyTargetUnitOfWork(TargetUnitOfWork):
    def __init__(self, database: Database) -> None:
        self._db = database

    @asynccontextmanager
    async def for_owner(self, owner_id: uuid.UUID) -> AsyncIterator[SqlAlchemyOwnerTarget]:
        async with self._db.for_user(owner_id) as session:
            yield SqlAlchemyOwnerTarget(session, owner_id)
