"""Gap plan HTTP surface: plan a route to a Target, then work through it."""

from __future__ import annotations

import uuid

from fastapi import APIRouter

from api.dependencies import CurrentUser, Deps, Paging, TargetQuery
from api.schemas.common import TargetEstimate
from api.schemas.gapplan import Plan, PlanSummary, PlanSummaryPage, TargetRequest, TaskDoneRequest
from wiring.queue import enqueue

router = APIRouter(tags=["gapplan"])


@router.get("/gap-plans/cost-estimate")
async def cost_estimate(target: TargetQuery, user: CurrentUser, deps: Deps) -> TargetEstimate:
    """Drafting runs on the user's key, so it is priced first."""
    return TargetEstimate.model_validate(await deps.gapplan.estimate_cost(user, target))


@router.post("/gap-plans", status_code=202)
async def request_plan(body: TargetRequest, user: CurrentUser, deps: Deps) -> PlanSummary:
    """Records the plan as drafting and queues it; poll ``GET /gap-plans/{id}``."""
    plan = await deps.gapplan.request(user, body.ref())
    await enqueue("gapplan.draft", owner_id=str(user), plan_id=str(plan.id))
    return PlanSummary.from_view(plan)


@router.get("/gap-plans")
async def history(user: CurrentUser, deps: Deps, paging: Paging) -> PlanSummaryPage:
    """Plan history: each Target's latest version, newest first."""
    found = await deps.gapplan.history(user, page=paging.page, page_size=paging.page_size)
    return PlanSummaryPage.of(found, PlanSummary.from_view)


@router.get("/gap-plans/{plan_id}")
async def get_plan(plan_id: uuid.UUID, user: CurrentUser, deps: Deps) -> Plan:
    return Plan.from_plan(await deps.gapplan.get(user, plan_id))


@router.put("/gap-plan-tasks/{task_id}", status_code=204)
async def set_task_done(
    task_id: uuid.UUID, body: TaskDoneRequest, user: CurrentUser, deps: Deps
) -> None:
    await deps.gapplan.set_task_done(user, task_id, body.done)
