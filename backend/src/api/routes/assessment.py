"""Assessment HTTP surface: the analysis and the radar."""

from __future__ import annotations

import uuid

from fastapi import APIRouter

from api.dependencies import CurrentUser, Deps, Paging
from api.schemas.activity import RunStatus
from api.schemas.assessment import Assessment, AssessmentPage
from api.schemas.common import CostEstimate
from wiring.queue import enqueue

router = APIRouter(tags=["assessment"])


@router.get("/assessments/cost-estimate")
async def cost_estimate(user: CurrentUser, deps: Deps) -> CostEstimate:
    """An analysis is priced and confirmed before it runs. It is the analysis
    alone: no role-map build follows it (ADR 0071)."""
    return CostEstimate.model_validate(await deps.assessment.estimate_cost(user))


@router.post("/assessments/runs/{run_id}/cancel", status_code=204)
async def cancel_run(run_id: uuid.UUID, user: CurrentUser, deps: Deps) -> None:
    """Stop an analysis, and a role-map build waiting for it (ADR 0072). A
    call already sent is still charged. Cancelling a closed run does nothing;
    another owner's run is not found."""
    await deps.activity.cancel_analysis(user, run_id)


@router.post("/assessments", status_code=202)
async def run_assessment(user: CurrentUser, deps: Deps) -> RunStatus:
    """Record the analysis as running and queue it. Refused with
    ``sources_processing`` while a source is still syncing or parsing, and
    ``analysis_running`` while one is already running (ADR 0018)."""
    run = await deps.activity.request_analysis(user)
    await enqueue("assessment.run", owner_id=str(user), run_id=str(run.id))
    return RunStatus.from_analysis(run)


@router.get("/assessments/latest")
async def latest(user: CurrentUser, deps: Deps) -> Assessment | None:
    assessment = await deps.assessment.latest(user)
    return Assessment.from_view(assessment) if assessment is not None else None


@router.get("/assessments")
async def history(user: CurrentUser, deps: Deps, paging: Paging) -> AssessmentPage:
    """Every analysis, newest first."""
    found = await deps.assessment.history(user, page=paging.page, page_size=paging.page_size)
    return AssessmentPage.of(found, Assessment.from_view)


__all__ = ["router"]
