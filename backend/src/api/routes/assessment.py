"""Assessment HTTP surface: the radar and the fits."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from api.dependencies import CurrentUser, Deps, Paging
from api.schemas.activity import RunStatus
from api.schemas.assessment import (
    Assessment,
    AssessmentPage,
    Fit,
    FitPage,
    MatchedPosting,
    MatchedPostingPage,
)
from api.schemas.common import Accepted, AnalysisEstimate
from kernel.paging import paginate
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


@router.get("/fits")
async def fits(user: CurrentUser, deps: Deps, paging: Paging) -> FitPage:
    """Bubble sizes. Fit belongs to the User x Role pair, never to the role."""
    # Paged here, not in the service: other components read the fits whole.
    found = paginate(await deps.assessment.fits(user), paging.page, paging.page_size)
    return FitPage.of(found, Fit.from_view)


@router.get("/matched-postings")
async def matched_postings(
    user: CurrentUser,
    deps: Deps,
    paging: Paging,
    role_id: Annotated[uuid.UUID | None, Query()] = None,
) -> MatchedPostingPage:
    """The openings inside the user's roles, best first, for the role map's "Top
    matched" list: ask for ``page_size=10`` for the top ten. ``role_id`` keeps
    one role's, the openings the Advisor can aim at in it. Ranked by the role's
    fit; no AI runs to produce it."""
    ranked = await deps.assessment.matched_postings(user, limit=None, role_id=role_id)
    return MatchedPostingPage.of(
        paginate(ranked, paging.page, paging.page_size), MatchedPosting.from_view
    )


@router.post("/fits/compute", status_code=202)
async def compute_fits(user: CurrentUser, deps: Deps) -> Accepted:
    await enqueue("assessment.compute_fits", owner_id=str(user))
    return Accepted()


__all__ = ["router"]
