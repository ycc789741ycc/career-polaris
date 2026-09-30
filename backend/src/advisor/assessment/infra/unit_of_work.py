"""Assessment's unit of work over SQL: one owner-zone transaction per scope.

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

from advisor.assessment.domain import (
    AnalysisFinished,
    AssessmentCompleted,
    AssessmentEvent,
    AssessmentUnitOfWork,
    DimensionsChanged,
    OwnerAssessment,
    RoleFitsComputed,
)
from advisor.assessment.infra.repositories import (
    SqlAlchemyAnalysisRunRepository,
    SqlAlchemyAssessedScoreRepository,
    SqlAlchemyDimensionChangeRepository,
    SqlAlchemyRoleFitRepository,
    SqlAlchemySkillAssessmentRepository,
    SqlAlchemySkillDimensionRepository,
)
from kernel.db import Database
from kernel.outbox import EventName, emit


class SqlAlchemyOwnerAssessment(OwnerAssessment):
    def __init__(self, session: AsyncSession, owner_id: uuid.UUID) -> None:
        self.dimensions = SqlAlchemySkillDimensionRepository(session, owner_id=owner_id)
        self.assessments = SqlAlchemySkillAssessmentRepository(session, owner_id=owner_id)
        self.scores = SqlAlchemyAssessedScoreRepository(session, owner_id=owner_id)
        self.changes = SqlAlchemyDimensionChangeRepository(session, owner_id=owner_id)
        self.runs = SqlAlchemyAnalysisRunRepository(session, owner_id=owner_id)
        self.fits = SqlAlchemyRoleFitRepository(session, owner_id=owner_id)
        self.pending: list[AssessmentEvent] = []

    def record(self, event: AssessmentEvent) -> None:
        self.pending.append(event)


class SqlAlchemyAssessmentUnitOfWork(AssessmentUnitOfWork):
    def __init__(self, database: Database) -> None:
        self._db = database

    @asynccontextmanager
    async def for_owner(self, owner_id: uuid.UUID) -> AsyncIterator[SqlAlchemyOwnerAssessment]:
        async with self._db.for_user(owner_id) as session:
            scope = SqlAlchemyOwnerAssessment(session, owner_id)
            yield scope
            for event in scope.pending:
                name, payload, owner = _outbox_entry(event)
                await emit(session, name, payload, owner_id=owner)


def _outbox_entry(event: AssessmentEvent) -> tuple[EventName, dict[str, Any], uuid.UUID]:
    """The outbox name, payload and routing owner for each assessment event.

    These payloads are a contract with the dispatcher and must not drift.
    """
    match event:
        case AssessmentCompleted():
            return (
                EventName.ASSESSMENT_COMPLETED,
                {
                    "assessment_id": str(event.assessment_id),
                    "dimensions": event.dimensions,
                    "model_id": event.model_id,
                },
                event.owner_id,
            )
        case AnalysisFinished():
            return (
                EventName.ANALYSIS_FINISHED,
                {
                    "run_id": str(event.run_id),
                    "status": event.status,
                    "error_code": event.error_code,
                },
                event.owner_id,
            )
        case DimensionsChanged():
            return (
                EventName.DIMENSIONS_CHANGED,
                {"added_or_renamed": event.added_or_renamed, "retired": event.retired},
                event.owner_id,
            )
        case RoleFitsComputed():
            return EventName.ROLE_FITS_COMPUTED, {"roles": event.roles}, event.owner_id
        case _:
            assert_never(event)
