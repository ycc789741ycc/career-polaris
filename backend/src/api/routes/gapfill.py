"""Fill the gap HTTP surface: questions per gap of one Target, and the one
submit that records the answers as evidence (ADR 0023)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from advisor.gapfill import Answer
from advisor.target import TargetRef
from api.dependencies import CurrentUser, Deps
from api.schemas.common import TargetEstimate
from api.schemas.gapfill import (
    AnswersRequest,
    QuestionSet,
    QuestionSetRequest,
    SubmitEstimate,
    Submitted,
)
from wiring.queue import enqueue

router = APIRouter(tags=["gapfill"])


@router.get("/gap-question-sets/current")
async def current_set(
    role_id: Annotated[uuid.UUID, Query()],
    user: CurrentUser,
    deps: Deps,
    job_posting_id: Annotated[uuid.UUID | None, Query()] = None,
) -> QuestionSet | None:
    """The Target's current questions; ``null`` before any were written."""
    found = await deps.gapfill.current(user, _ref(role_id, job_posting_id))
    return QuestionSet.from_view(found) if found is not None else None


@router.get("/gap-question-sets/cost-estimate")
async def cost_estimate(
    role_id: Annotated[uuid.UUID, Query()],
    user: CurrentUser,
    deps: Deps,
    job_posting_id: Annotated[uuid.UUID | None, Query()] = None,
) -> TargetEstimate:
    """Writing the questions runs on the user's key, so it is priced first."""
    return TargetEstimate.model_validate(
        await deps.gapfill.estimate_cost(user, _ref(role_id, job_posting_id))
    )


@router.post("/gap-question-sets", status_code=202)
async def request_set(body: QuestionSetRequest, user: CurrentUser, deps: Deps) -> QuestionSet:
    """Records the set as writing and queues it; poll ``GET /gap-question-sets/{id}``."""
    found = await deps.gapfill.request(user, _ref(body.role_id, body.job_posting_id))
    await enqueue("gapfill.write", owner_id=str(user), set_id=str(found.id))
    return QuestionSet.from_view(found)


@router.get("/gap-question-sets/{set_id}")
async def get_set(set_id: uuid.UUID, user: CurrentUser, deps: Deps) -> QuestionSet:
    return QuestionSet.from_view(await deps.gapfill.get(user, set_id))


@router.get("/gap-question-sets/{set_id}/submit-estimate")
async def submit_estimate(set_id: uuid.UUID, user: CurrentUser, deps: Deps) -> SubmitEstimate:
    """Submitting writes the Target's plan and résumé again, each only if the
    user has one; that is what it costs."""
    ref = (await deps.gapfill.get(user, set_id)).target
    plan = (
        await deps.gapplan.estimate_cost(user, ref)
        if await deps.gapplan.latest_for(user, ref) is not None
        else None
    )
    resume = (
        await deps.resume.estimate_cost(user, ref)
        if await deps.resume.latest_for(user, ref) is not None
        else None
    )
    return SubmitEstimate.of(plan=plan, resume=resume)


@router.post("/gap-question-sets/{set_id}/answers")
async def submit(
    set_id: uuid.UUID, body: AnswersRequest, user: CurrentUser, deps: Deps
) -> Submitted:
    """Every answer at once: checked as a batch, stored as ``user_answer``
    evidence, then the Target's plan and résumé are written again."""
    done = await deps.gapfill.submit(
        user,
        set_id,
        [Answer(question_id=a.question_id, choice=a.choice, text=a.text) for a in body.answers],
    )
    return Submitted.from_view(done)


def _ref(role_id: uuid.UUID, job_posting_id: uuid.UUID | None) -> TargetRef:
    return TargetRef(str(role_id), str(job_posting_id) if job_posting_id else None)
