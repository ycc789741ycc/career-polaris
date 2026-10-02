"""How the gap plan's use cases reach stored data: interfaces in domain terms.

Every repository has the same six methods (ADR 0011): ``create``, ``get``,
``get_list`` (newest first, paged), ``get_count``, ``update`` and ``delete``,
over one frozen filter per aggregate whose unset fields do not filter.
Milestones and tasks have no creation time stored, so they list by id; the use
cases order them by position.

All plan data is owner-zone, so the unit of work has one scope: one user's data,
in one transaction. Events recorded in it are committed with it.
"""

from __future__ import annotations

import uuid
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Protocol

from advisor.gapplan.domain.events import GapPlanEvent
from advisor.gapplan.domain.plan import GapPlan, Milestone, Task


class Repository[Entity, Filter](Protocol):
    """The six methods, as every gap-plan repository has them."""

    async def create(self, entity: Entity) -> Entity: ...

    async def get(self, entity_id: uuid.UUID) -> Entity | None: ...

    async def get_list(
        self, filter: Filter, page: int = 1, page_size: int | None = None
    ) -> list[Entity]: ...

    async def get_count(self, filter: Filter) -> int: ...

    async def update(self, entity: Entity) -> Entity: ...

    async def delete(self, entity_id: uuid.UUID) -> None: ...


@dataclass(frozen=True, slots=True)
class GapPlanFilter:
    """``role_only`` narrows a ``role_id`` to plans aimed at the role itself,
    with no opening; otherwise ``job_posting_id`` picks one opening."""

    role_id: uuid.UUID | None = None
    job_posting_id: uuid.UUID | None = None
    role_only: bool = False


class GapPlanRepository(Repository[GapPlan, GapPlanFilter], Protocol): ...


@dataclass(frozen=True, slots=True)
class MilestoneFilter:
    plan_id: uuid.UUID | None = None


class MilestoneRepository(Repository[Milestone, MilestoneFilter], Protocol): ...


@dataclass(frozen=True, slots=True)
class TaskFilter:
    plan_ids: tuple[uuid.UUID, ...] | None = None
    is_done: bool | None = None


class TaskRepository(Repository[Task, TaskFilter], Protocol): ...


class OwnerGapPlans(Protocol):
    plans: GapPlanRepository
    milestones: MilestoneRepository
    tasks: TaskRepository

    def record(self, event: GapPlanEvent) -> None: ...


class GapPlanUnitOfWork(Protocol):
    def for_owner(self, owner_id: uuid.UUID) -> AbstractAsyncContextManager[OwnerGapPlans]: ...
