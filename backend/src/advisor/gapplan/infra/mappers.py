"""ORM rows to gap-plan entities and back. No rules live here, only shape.

A plan's Target is a role and an optional opening, or a posting of the user's
own, as three columns.
"""

from __future__ import annotations

from advisor.gapplan.domain import GapPlan, Milestone, PlanStatus, Task
from advisor.gapplan.infra import models


def plan(row: models.GapPlan) -> GapPlan:
    return GapPlan(
        id=row.id,
        owner_id=row.owner_id,
        role_id=row.role_id,
        job_posting_id=row.job_posting_id,
        private_job_posting_id=row.private_job_posting_id,
        target_label=row.target_label,
        version=row.version,
        status=PlanStatus(row.status),
        created_at=row.created_at,
        error_code=row.error_code,
        error_message=row.error_message,
        snapshot=dict(row.snapshot) if row.snapshot is not None else None,
        gaps=tuple(row.gaps),
        projects=tuple(row.projects),
        stepping_stones=tuple(row.stepping_stones),
        model_id=row.model_id,
        template_version=row.template_version,
        drafted_at=row.drafted_at,
        profile_version=row.profile_version,
        target_digest=row.target_digest,
    )


def plan_row(entity: GapPlan) -> models.GapPlan:
    row = models.GapPlan(
        id=entity.id,
        owner_id=entity.owner_id,
        role_id=entity.role_id,
        job_posting_id=entity.job_posting_id,
        private_job_posting_id=entity.private_job_posting_id,
        created_at=entity.created_at,
    )
    apply_plan(row, entity)
    return row


def apply_plan(row: models.GapPlan, entity: GapPlan) -> None:
    row.target_label = entity.target_label
    row.version = entity.version
    row.status = str(entity.status)
    row.error_code = entity.error_code
    row.error_message = entity.error_message
    row.snapshot = entity.snapshot
    row.gaps = list(entity.gaps)
    row.projects = list(entity.projects)
    row.stepping_stones = list(entity.stepping_stones)
    row.model_id = entity.model_id
    row.template_version = entity.template_version
    row.drafted_at = entity.drafted_at
    row.profile_version = entity.profile_version
    row.target_digest = entity.target_digest


def milestone(row: models.Milestone) -> Milestone:
    return Milestone(
        id=row.id,
        owner_id=row.owner_id,
        plan_id=row.plan_id,
        position=row.position,
        title=row.title,
        time_window=row.time_window,
        outcome=row.outcome,
    )


def milestone_row(entity: Milestone) -> models.Milestone:
    row = models.Milestone(id=entity.id, owner_id=entity.owner_id, plan_id=entity.plan_id)
    apply_milestone(row, entity)
    return row


def apply_milestone(row: models.Milestone, entity: Milestone) -> None:
    row.position = entity.position
    row.title = entity.title
    row.time_window = entity.time_window
    row.outcome = entity.outcome


def task(row: models.Task) -> Task:
    return Task(
        id=row.id,
        owner_id=row.owner_id,
        plan_id=row.plan_id,
        milestone_id=row.milestone_id,
        position=row.position,
        text=row.text,
        due=row.due,
        closes=tuple(row.closes),
        done_at=row.done_at,
    )


def task_row(entity: Task) -> models.Task:
    row = models.Task(
        id=entity.id,
        owner_id=entity.owner_id,
        plan_id=entity.plan_id,
        milestone_id=entity.milestone_id,
    )
    apply_task(row, entity)
    return row


def apply_task(row: models.Task, entity: Task) -> None:
    row.position = entity.position
    row.text = entity.text
    row.due = entity.due
    row.closes = list(entity.closes)
    row.done_at = entity.done_at
