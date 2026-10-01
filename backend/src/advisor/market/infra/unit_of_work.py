"""The market's unit of work over SQL: one transaction per scope.

Each scope opens exactly the session the use case used to open itself —
``for_user`` or ``shared`` from ``kernel.db`` — so row-level security applies
as before. Events recorded in a scope go
to the outbox in the same transaction, just before it commits.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, assert_never

from sqlalchemy.ext.asyncio import AsyncSession

from advisor.market.domain import (
    MarketEvent,
    MarketUnitOfWork,
    OwnerMarket,
    SharedMarket,
    TargetLocationsChanged,
)
from advisor.market.infra.repositories import (
    SqlAlchemyCompanyRepository,
    SqlAlchemyCrawlSourceRepository,
    SqlAlchemyJobPostingRepository,
    SqlAlchemyMarketPreferenceRepository,
    SqlAlchemyPostingEmbeddingRepository,
    SqlAlchemyPrivateJobPostingRepository,
    SqlAlchemySearchResultRepository,
)
from kernel.db import Database
from kernel.outbox import EventName, emit


class _Events:
    def __init__(self) -> None:
        self.pending: list[MarketEvent] = []

    def record(self, event: MarketEvent) -> None:
        self.pending.append(event)

    async def flush(self, session: AsyncSession) -> None:
        for event in self.pending:
            name, payload, owner_id = _outbox_entry(event)
            await emit(session, name, payload, owner_id=owner_id)
        self.pending.clear()


class SqlAlchemySharedMarket(_Events, SharedMarket):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__()
        self.companies = SqlAlchemyCompanyRepository(session)
        self.sources = SqlAlchemyCrawlSourceRepository(session)
        self.postings = SqlAlchemyJobPostingRepository(session)
        self.embeddings = SqlAlchemyPostingEmbeddingRepository(session)
        self.search_results = SqlAlchemySearchResultRepository(session)


class SqlAlchemyOwnerMarket(_Events, OwnerMarket):
    def __init__(self, session: AsyncSession, owner_id: uuid.UUID) -> None:
        super().__init__()
        self.markets = SqlAlchemyMarketPreferenceRepository(session, owner_id=owner_id)
        self.private_postings = SqlAlchemyPrivateJobPostingRepository(session, owner_id=owner_id)


class SqlAlchemyMarketUnitOfWork(MarketUnitOfWork):
    def __init__(self, database: Database) -> None:
        self._db = database

    @asynccontextmanager
    async def for_owner(self, owner_id: uuid.UUID) -> AsyncIterator[SqlAlchemyOwnerMarket]:
        async with self._db.for_user(owner_id) as session:
            scope = SqlAlchemyOwnerMarket(session, owner_id)
            yield scope
            await scope.flush(session)

    @asynccontextmanager
    async def shared(self) -> AsyncIterator[SqlAlchemySharedMarket]:
        async with self._db.shared() as session:
            scope = SqlAlchemySharedMarket(session)
            yield scope
            await scope.flush(session)


def _outbox_entry(event: MarketEvent) -> tuple[EventName, dict[str, Any], uuid.UUID | None]:
    """The outbox name, payload and routing owner for each market event.

    These payloads are a contract with the dispatcher and must not drift.
    """
    match event:
        case TargetLocationsChanged():
            return (
                EventName.TARGET_LOCATIONS_CHANGED,
                {"locations": list(event.locations)},
                event.owner_id,
            )
        case _:
            assert_never(event)
