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


@router.post("/gap-question-sets/{set_id}/answers")
async def submit(
    set_id: uuid.UUID, body: AnswersRequest, user: CurrentUser, deps: Deps
) -> Submitted:
    """Every answer at once: checked as a batch and stored as ``user_answer``
    evidence. Spends nothing and rewrites nothing: the Target's plan and résumé
    then read as outdated, and the user regenerates them (ADR 0035)."""
    done = await deps.gapfill.submit(
        user,
        set_id,
        [Answer(question_id=a.question_id, choice=a.choice, text=a.text) for a in body.answers],
    )
    return Submitted.from_view(done)
