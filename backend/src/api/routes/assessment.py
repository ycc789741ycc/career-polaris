"""Assessment HTTP surface: the radar, the follow-up questions and the fits."""

from __future__ import annotations

import uuid

from fastapi import APIRouter

from api.dependencies import CurrentUser, Deps, Paging
from api.schemas.assessment import (
    AnswerRequest,
    Assessment,
    AssessmentPage,
    Fit,
    FitPage,
    MatchedPosting,
    MatchedPostingPage,
    Question,
    QuestionPage,
    QuestionStatus,
)
from api.schemas.common import Accepted, CostEstimate
from kernel.paging import paginate
from wiring.queue import enqueue

router = APIRouter(tags=["assessment"])


@router.get("/assessments/cost-estimate")
async def cost_estimate(user: CurrentUser, deps: Deps) -> CostEstimate:
    """The first analysis is priced and confirmed before it runs."""
    return CostEstimate.model_validate(await deps.assessment.estimate_cost(user))


@router.post("/assessments", status_code=202)
async def run_assessment(user: CurrentUser, deps: Deps) -> Accepted:
    await enqueue("assessment.run", owner_id=str(user))
    return Accepted()


@router.get("/assessments/latest")
async def latest(user: CurrentUser, deps: Deps) -> Assessment | None:
    assessment = await deps.assessment.latest(user)
    return Assessment.from_view(assessment) if assessment is not None else None


@router.get("/assessments")
async def history(user: CurrentUser, deps: Deps, paging: Paging) -> AssessmentPage:
    """Every analysis, newest first."""
    found = await deps.assessment.history(user, page=paging.page, page_size=paging.page_size)
    return AssessmentPage.of(found, Assessment.from_view)


@router.get("/questions")
async def questions(user: CurrentUser, deps: Deps, paging: Paging) -> QuestionPage:
    """Open follow-up questions, oldest first."""
    found = await deps.assessment.questions(user, page=paging.page, page_size=paging.page_size)
    return QuestionPage.of(found, Question.from_view)


@router.get("/questions/status")
async def question_status(user: CurrentUser, deps: Deps) -> QuestionStatus | None:
    """The newest question round, which the page polls while it is
    ``generating`` (ADR 0006, ADR 0012). ``null`` before the first one."""
    found = await deps.assessment.latest_round(user)
    return QuestionStatus.from_view(found) if found is not None else None


@router.post("/questions/{question_id}/answer", status_code=202)
async def answer(
    question_id: uuid.UUID, body: AnswerRequest, user: CurrentUser, deps: Deps
) -> Accepted:
    """An answer becomes self-reported Evidence, then the analysis re-runs and
    opens a new question round."""
    await deps.assessment.answer(user, question_id, body.answer)
    await enqueue("assessment.run", owner_id=str(user))
    return Accepted()


@router.get("/fits")
async def fits(user: CurrentUser, deps: Deps, paging: Paging) -> FitPage:
    """Bubble sizes. Fit belongs to the User x Role pair, never to the role."""
    # Paged here, not in the service: other components read the fits whole.
    found = paginate(await deps.assessment.fits(user), paging.page, paging.page_size)
    return FitPage.of(found, Fit.from_view)


@router.get("/matched-postings")
async def matched_postings(user: CurrentUser, deps: Deps, paging: Paging) -> MatchedPostingPage:
    """The openings inside the user's roles, best first, for the role map's "Top
    matched" list: ask for ``page_size=10`` for the top ten. Ranked by the
    role's fit; no AI runs to produce it."""
    ranked = await deps.assessment.matched_postings(user, limit=None)
    return MatchedPostingPage.of(
        paginate(ranked, paging.page, paging.page_size), MatchedPosting.from_view
    )


@router.post("/fits/compute", status_code=202)
async def compute_fits(user: CurrentUser, deps: Deps) -> Accepted:
    await enqueue("assessment.compute_fits", owner_id=str(user))
    return Accepted()


__all__ = ["router"]
