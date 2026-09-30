"""SQLAlchemy implementations of the gap plan's repositories.

The six methods come from ``kernel.db.repository.SqlAlchemyRepository``. Every
plan table is owner-zone, so every repository here is bound to one owner.
Milestones and tasks have no creation time stored, so they sort by id.
"""

from __future__ import annotations

import uuid
from typing import ClassVar

from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.elements import ColumnElement

from advisor.gapplan.domain import (
    GapPlan,
    GapPlanFilter,
    GapPlanRepository,
    Milestone,
    MilestoneFilter,
    MilestoneRepository,
    Task,
    TaskFilter,
    TaskRepository,
)
from advisor.gapplan.infra import mappers, models
from kernel.db.repository import SqlAlchemyRepository


class SqlAlchemyGapPlanRepository(
    SqlAlchemyRepository[GapPlan, models.GapPlan, GapPlanFilter],
    GapPlanRepository,
):
    model = models.GapPlan
    id_column = models.GapPlan.id
    created_column = models.GapPlan.created_at
    owner_column: ClassVar[InstrumentedAttribute[uuid.UUID] | None] = models.GapPlan.owner_id
    noun = "plan"

    def to_entity(self, row: models.GapPlan) -> GapPlan:
        return mappers.plan(row)

    def to_row(self, entity: GapPlan) -> models.GapPlan:
        return mappers.plan_row(entity)

    def apply(self, row: models.GapPlan, entity: GapPlan) -> None:
        mappers.apply_plan(row, entity)

    def id_of(self, entity: GapPlan) -> uuid.UUID:
        return entity.id

    def conditions(self, filter: GapPlanFilter) -> list[ColumnElement[bool]]:
        plan = models.GapPlan
        found: list[ColumnElement[bool]] = []
        if filter.role_id is not None:
            found.append(plan.role_id == filter.role_id)
        if filter.job_posting_id is not None:
            found.append(plan.job_posting_id == filter.job_posting_id)
        elif filter.role_only:
            found.append(plan.job_posting_id.is_(None))
        return found


class SqlAlchemyMilestoneRepository(
    SqlAlchemyRepository[Milestone, models.Milestone, MilestoneFilter],
    MilestoneRepository,
):
    model = models.Milestone
    id_column = models.Milestone.id
    created_column = models.Milestone.id
    owner_column: ClassVar[InstrumentedAttribute[uuid.UUID] | None] = models.Milestone.owner_id
    noun = "milestone"

    def to_entity(self, row: models.Milestone) -> Milestone:
        return mappers.milestone(row)

    def to_row(self, entity: Milestone) -> models.Milestone:
        return mappers.milestone_row(entity)

    def apply(self, row: models.Milestone, entity: Milestone) -> None:
        mappers.apply_milestone(row, entity)

    def id_of(self, entity: Milestone) -> uuid.UUID:
        return entity.id

    def conditions(self, filter: MilestoneFilter) -> list[ColumnElement[bool]]:
        if filter.plan_id is None:
            return []
        return [models.Milestone.plan_id == filter.plan_id]


class SqlAlchemyTaskRepository(SqlAlchemyRepository[Task, models.Task, TaskFilter], TaskRepository):
    model = models.Task
    id_column = models.Task.id
    created_column = models.Task.id
    owner_column: ClassVar[InstrumentedAttribute[uuid.UUID] | None] = models.Task.owner_id
    noun = "task"

    def to_entity(self, row: models.Task) -> Task:
        return mappers.task(row)

    def to_row(self, entity: Task) -> models.Task:
        return mappers.task_row(entity)

    def apply(self, row: models.Task, entity: Task) -> None:
        mappers.apply_task(row, entity)

    def id_of(self, entity: Task) -> uuid.UUID:
        return entity.id

    def conditions(self, filter: TaskFilter) -> list[ColumnElement[bool]]:
        found: list[ColumnElement[bool]] = []
        if filter.plan_ids is not None:
            found.append(models.Task.plan_id.in_(filter.plan_ids))
        if filter.is_done is True:
            found.append(models.Task.done_at.is_not(None))
        elif filter.is_done is False:
            found.append(models.Task.done_at.is_(None))
        return found
