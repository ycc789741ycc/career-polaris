"""Assessment HTTP surface: the analysis and the radar."""

from __future__ import annotations

from fastapi import APIRouter

from api.dependencies import CurrentUser, Deps, Paging
from api.schemas.activity import RunStatus
from api.schemas.assessment import Assessment, AssessmentPage
from api.schemas.common import AnalysisEstimate
from wiring.queue import enqueue

router = APIRouter(tags=["assessment"])


@router.get("/assessments/cost-estimate")
async def cost_estimate(user: CurrentUser, deps: Deps) -> AnalysisEstimate:
    """An analysis is priced and confirmed before it runs, with the role-map
    build that follows it."""
    return AnalysisEstimate.model_validate(await deps.assessment.estimate_cost(user))


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
