"""Fill the gap HTTP surface: questions per gap of one Target, and the one
submit that records the answers as evidence (ADR 0023)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter

from advisor.gapfill import Answer
from api.dependencies import CurrentUser, Deps, TargetQuery
from api.schemas.common import TargetEstimate
from api.schemas.gapfill import (
    AnswersRequest,
    QuestionSet,
    QuestionSetRequest,
    Submitted,
)
from wiring.queue import enqueue

router = APIRouter(tags=["gapfill"])


@router.get("/gap-question-sets/current")
async def current_set(target: TargetQuery, user: CurrentUser, deps: Deps) -> QuestionSet | None:
    """The Target's current questions; ``null`` before any were written."""
    found = await deps.gapfill.current(user, target)
    return QuestionSet.from_view(found) if found is not None else None


@router.get("/gap-question-sets/cost-estimate")
async def cost_estimate(target: TargetQuery, user: CurrentUser, deps: Deps) -> TargetEstimate:
    """Writing the questions runs on the user's key, so it is priced first."""
    return TargetEstimate.model_validate(await deps.gapfill.estimate_cost(user, target))


@router.post("/gap-question-sets", status_code=202)
async def request_set(body: QuestionSetRequest, user: CurrentUser, deps: Deps) -> QuestionSet:
    """Records the set as writing and queues it; poll ``GET /gap-question-sets/{id}``."""
    found = await deps.gapfill.request(user, body.ref())
    await enqueue("gapfill.write", owner_id=str(user), set_id=str(found.id))
    return QuestionSet.from_view(found)


@router.get("/gap-question-sets/{set_id}")
async def get_set(set_id: uuid.UUID, user: CurrentUser, deps: Deps) -> QuestionSet:
    return QuestionSet.from_view(await deps.gapfill.get(user, set_id))


@router.post("/gap-question-sets/{set_id}/cancel", status_code=204)
async def cancel_set(set_id: uuid.UUID, user: CurrentUser, deps: Deps) -> None:
    """Stops writing the questions before the next call or the save (ADR
    0042). A call already sent is still charged."""
    await deps.gapfill.cancel(user, set_id)


@router.get("/gap-question-sets/{set_id}/fit-reading-estimate")
async def fit_reading_estimate(set_id: uuid.UUID, user: CurrentUser, deps: Deps) -> TargetEstimate:
    """Reading the answers into the fit runs on the user's key, so it is
    priced before they are submitted: a ceiling (ADR 0077)."""
    return TargetEstimate.model_validate(await deps.gapfill.estimate_fit_reading(user, set_id))


@router.post("/gap-question-sets/{set_id}/answers")
async def submit(
    set_id: uuid.UUID, body: AnswersRequest, user: CurrentUser, deps: Deps
) -> Submitted:
    """Every answer at once: checked as a batch and stored as ``user_answer``
    evidence. With ``update_fit``, then read into the Target's fit by a job
    the set reports (ADR 0077); the plan and résumé read as outdated either
    way, and the user regenerates them (ADR 0035)."""
    done = await deps.gapfill.submit(
        user,
        set_id,
        [Answer(question_id=a.question_id, choice=a.choice, text=a.text) for a in body.answers],
    )
    if body.update_fit:
        await deps.gapfill.start_fit_reading(user, set_id)
        await enqueue("gapfill.read_answers", owner_id=str(user), set_id=str(set_id))
    return Submitted.from_view(done)


@router.post("/gap-question-sets/{set_id}/fit-reading", status_code=202)
async def read_answers(set_id: uuid.UUID, user: CurrentUser, deps: Deps) -> QuestionSet:
    """Read a submitted set's answers into the fit again, after a failure or
    a cancel (ADR 0077); priced first, like the submit."""
    found = await deps.gapfill.start_fit_reading(user, set_id)
    await enqueue("gapfill.read_answers", owner_id=str(user), set_id=str(set_id))
    return QuestionSet.from_view(found)
