"""The SQLAlchemy side of the gap plan's repositories, against a real database.

Worth proving here: a plan's Target lands in the right reference column for
each kind and reads back as a kind and an id, the same-target filter finds only
that Target's versions, and the drafted event lands in the outbox as the
dispatcher reads it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text

from advisor.gapplan.domain import (
    GapPlan,
    GapPlanFilter,
    Milestone,
    PlanDrafted,
    PlanStatus,
    Task,
    TaskFilter,
)
from advisor.gapplan.infra.unit_of_work import SqlAlchemyGapPlanUnitOfWork
from kernel.db import Database

pytestmark = pytest.mark.integration

AT = datetime(2026, 9, 27, tzinfo=UTC)


async def test_a_plans_target_is_a_role_and_an_optional_opening(
    database: Database, account: uuid.UUID
) -> None:
    uow = SqlAlchemyGapPlanUnitOfWork(database)
    role, opening = uuid.uuid4(), uuid.uuid4()

    def requested(job_posting_id: uuid.UUID | None, label: str) -> GapPlan:
        return GapPlan.requested(
            owner_id=account,
            role_id=role,
            job_posting_id=job_posting_id,
            label=label,
            version=1,
            at=AT,
        )

    async with uow.for_owner(account) as mine:
        for_role = await mine.plans.create(requested(None, "Staff Engineer"))
        for_opening = await mine.plans.create(requested(opening, "Staff Engineer · Acme"))

    async with uow.for_owner(account) as mine:
        assert await mine.plans.get_list(GapPlanFilter(role_id=role, role_only=True)) == [for_role]
        assert await mine.plans.get_list(GapPlanFilter(role_id=role, job_posting_id=opening)) == [
            for_opening
        ]
        assert await mine.plans.get_count(GapPlanFilter(role_id=role)) == 2
    async with database.for_user(account) as session:
        stored = await session.execute(
            text("SELECT role_id, job_posting_id FROM gapplan.plan WHERE id = :id"),
            {"id": for_opening.id},
        )
        assert tuple(stored.one()) == (role, opening)


async def test_a_drafted_plan_its_tasks_and_its_event(
    database: Database, account: uuid.UUID
) -> None:
    uow = SqlAlchemyGapPlanUnitOfWork(database)
    async with uow.for_owner(account) as mine:
        plan = await mine.plans.create(
            GapPlan.requested(
                owner_id=account,
                role_id=uuid.uuid4(),
                job_posting_id=None,
                label="Platform role",
                version=2,
                at=AT,
            )
        )
        milestone = await mine.milestones.create(
            Milestone(
                id=uuid.uuid4(),
                owner_id=account,
                plan_id=plan.id,
                position=0,
                title="Month one",
                time_window="4 weeks",
                outcome="Shipped",
            )
        )
        task = await mine.tasks.create(
            Task(
                id=uuid.uuid4(),
                owner_id=account,
                plan_id=plan.id,
                milestone_id=milestone.id,
                position=0,
                text="Build an API",
                due="week 1",
                closes=("dim:api",),
                done_at=AT,
            )
        )
        plan.drafted(
            snapshot={"label": "Platform role"},
            label="Platform role",
            gaps=({"key": "dim:api", "lift": 5},),
            projects=(),
            stepping_stones=(),
            model_id="m",
            template_version="v1",
            at=AT,
        )
        await mine.plans.update(plan)
        mine.record(PlanDrafted(owner_id=account, plan_id=plan.id, role_id=plan.role_id, version=2))

    async with uow.for_owner(account) as mine:
        loaded = await mine.plans.get(plan.id)
        assert loaded is not None and loaded.status is PlanStatus.READY
        assert loaded.gaps == ({"key": "dim:api", "lift": 5},)
        assert await mine.tasks.get_list(TaskFilter(plan_ids=(plan.id,), is_done=True)) == [task]

    async with database.shared() as session:
        rows = await session.execute(
            text("SELECT name, payload FROM outbox.event WHERE owner_id = :owner"),
            {"owner": account},
        )
        assert [tuple(r) for r in rows.all()] == [
            (
                "PlanDrafted",
                {"plan_id": str(plan.id), "role_id": str(plan.role_id), "version": 2},
            )
        ]
