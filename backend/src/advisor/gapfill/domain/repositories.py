"""How Fill the gap's use cases reach stored data: interfaces in domain terms.

Every repository has the same six methods (ADR 0011): ``create``, ``get``,
``get_list`` (newest first, paged), ``get_count``, ``update`` and ``delete``,
over one frozen filter per aggregate whose unset fields do not filter.
Questions have no creation time stored, so they list by id; the use cases
order them by position.

All of it is owner-zone, so the unit of work has one scope: one user's data, in
one transaction. Events recorded in it are committed with it.
"""

from __future__ import annotations

import uuid
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Protocol

from advisor.gapfill.domain.events import GapFillEvent
from advisor.gapfill.domain.questions import GapQuestion, QuestionSet, QuestionSetStatus


class Repository[Entity, Filter](Protocol):
    """The six methods, as every Fill the gap repository has them."""

    async def create(self, entity: Entity) -> Entity: ...

    async def get(self, entity_id: uuid.UUID) -> Entity | None: ...

    async def get_list(
        self, filter: Filter, page: int = 1, page_size: int | None = None
    ) -> list[Entity]: ...

    async def get_count(self, filter: Filter) -> int: ...

    async def update(self, entity: Entity) -> Entity: ...

    async def delete(self, entity_id: uuid.UUID) -> None: ...


@dataclass(frozen=True, slots=True)
class QuestionSetFilter:
    """``role_only`` narrows a ``role_id`` to sets for the role itself, with no
    opening; otherwise ``job_posting_id`` picks one opening.
    ``private_job_posting_id`` picks a posting of the user's own."""

    role_id: uuid.UUID | None = None
    job_posting_id: uuid.UUID | None = None
    role_only: bool = False
    private_job_posting_id: uuid.UUID | None = None
    statuses: tuple[QuestionSetStatus, ...] | None = None


class QuestionSetRepository(Repository[QuestionSet, QuestionSetFilter], Protocol): ...


@dataclass(frozen=True, slots=True)
class GapQuestionFilter:
    set_ids: tuple[uuid.UUID, ...] | None = None


class GapQuestionRepository(Repository[GapQuestion, GapQuestionFilter], Protocol): ...


class OwnerGapFill(Protocol):
    sets: QuestionSetRepository
    questions: GapQuestionRepository

    def record(self, event: GapFillEvent) -> None: ...


class GapFillUnitOfWork(Protocol):
    def for_owner(self, owner_id: uuid.UUID) -> AbstractAsyncContextManager[OwnerGapFill]: ...
