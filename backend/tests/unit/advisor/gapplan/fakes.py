"""In-memory gap-plan storage: the domain's repository interfaces, with no database."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from advisor.gapplan.domain import (
    GapPlan,
    GapPlanEvent,
    GapPlanFilter,
    GapPlanRepository,
    GapPlanUnitOfWork,
    Milestone,
    MilestoneFilter,
    MilestoneRepository,
    OwnerGapPlans,
    Task,
    TaskFilter,
    TaskRepository,
)
from tests.unit.kernel.db.fake_repository import FakeRepository


@dataclass
class Store:
    plans: dict[uuid.UUID, GapPlan] = field(default_factory=dict)
    milestones: dict[uuid.UUID, Milestone] = field(default_factory=dict)
    tasks: dict[uuid.UUID, Task] = field(default_factory=dict)
    events: list[GapPlanEvent] = field(default_factory=list)


class FakePlans(FakeRepository[GapPlan, GapPlanFilter], GapPlanRepository):
    updated_field = None
    owner_field = "owner_id"
    noun = "plan"

    def matches(self, entity: GapPlan, filter: GapPlanFilter) -> bool:
        if filter.role_id is not None and entity.role_id != filter.role_id:
            return False
        if filter.job_posting_id is not None:
            return entity.job_posting_id == filter.job_posting_id
        return not filter.role_only or entity.job_posting_id is None


class FakeMilestones(FakeRepository[Milestone, MilestoneFilter], MilestoneRepository):
    created_field = "id"
    updated_field = None
    owner_field = "owner_id"
    noun = "milestone"

    def matches(self, entity: Milestone, filter: MilestoneFilter) -> bool:
        return filter.plan_id is None or entity.plan_id == filter.plan_id


class FakeTasks(FakeRepository[Task, TaskFilter], TaskRepository):
    created_field = "id"
    updated_field = None
    owner_field = "owner_id"
    noun = "task"

    def matches(self, entity: Task, filter: TaskFilter) -> bool:
        return (filter.plan_ids is None or entity.plan_id in filter.plan_ids) and (
            filter.is_done is None or (entity.done_at is not None) == filter.is_done
        )


class FakeOwner(OwnerGapPlans):
    def __init__(self, store: Store, owner_id: uuid.UUID) -> None:
        self.plans = FakePlans(store.plans, owner_id=owner_id)
        self.milestones = FakeMilestones(store.milestones, owner_id=owner_id)
        self.tasks = FakeTasks(store.tasks, owner_id=owner_id)
        self.pending: list[GapPlanEvent] = []

    def record(self, event: GapPlanEvent) -> None:
        self.pending.append(event)


class FakeGapPlanUnitOfWork(GapPlanUnitOfWork):
    def __init__(self, store: Store | None = None) -> None:
        self.store = store or Store()

    @asynccontextmanager
    async def for_owner(self, owner_id: uuid.UUID) -> AsyncIterator[FakeOwner]:
        scope = FakeOwner(self.store, owner_id)
        yield scope
        self.store.events.extend(scope.pending)
