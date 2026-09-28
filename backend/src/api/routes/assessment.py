"""Assessment HTTP surface: the radar, the follow-up questions and the fits."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from advisor.assessment import DEFAULT_MATCHES, MAX_MATCHES, MIN_MATCHES
from api.dependencies import CurrentUser, Deps
from api.schemas.assessment import (
    AnswerRequest,
    Assessment,
    Fit,
    MatchedPosting,
    Question,
    QuestionStatus,
)
from api.schemas.common import Accepted, CostEstimate
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
async def history(user: CurrentUser, deps: Deps) -> list[Assessment]:
    return [Assessment.from_view(a) for a in await deps.assessment.history(user)]


@router.get("/questions")
async def questions(user: CurrentUser, deps: Deps) -> list[Question]:
    return [Question.from_view(q) for q in await deps.assessment.questions(user)]


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
async def fits(user: CurrentUser, deps: Deps) -> list[Fit]:
    """Bubble sizes. Fit belongs to the User x Role pair, never to the role."""
    return [Fit.from_view(f) for f in await deps.assessment.fits(user)]


@router.get("/matched-postings")
async def matched_postings(
    user: CurrentUser,
    deps: Deps,
    limit: Annotated[int, Query(ge=MIN_MATCHES, le=MAX_MATCHES)] = DEFAULT_MATCHES,
) -> list[MatchedPosting]:
    """The best openings inside the user's roles, for the role map's "Top
    matched" list. Ranked by the role's fit; no AI runs to produce it."""
    return [
        MatchedPosting.from_view(m)
        for m in await deps.assessment.matched_postings(user, limit=limit)
    ]


@router.post("/fits/compute", status_code=202)
async def compute_fits(user: CurrentUser, deps: Deps) -> Accepted:
    await enqueue("assessment.compute_fits", owner_id=str(user))
    return Accepted()


__all__ = ["router"]
