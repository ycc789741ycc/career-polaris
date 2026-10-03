"""Target HTTP surface: the postings the user brings themselves to aim the
Advisor at (Phase 8, ADR 0033), uploaded as a file or filled in by hand, which
are never on the role map. Adding one spends nothing; setting it as the target
reads and scores it (ADR 0034)."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, File, Form, Query, UploadFile

from advisor.target import MAX_COMPANY_NAME, MAX_TITLE, TargetRef
from api.dependencies import CurrentUser, Deps, Paging
from api.schemas.target import (
    OwnPosting,
    OwnPostingEstimate,
    OwnPostingPage,
    OwnPostingRequest,
)
from kernel.paging import paginate
from wiring.queue import enqueue, queue_questions

router = APIRouter(tags=["target"])


@router.get("/own-postings")
async def own_postings(user: CurrentUser, deps: Deps, paging: Paging) -> OwnPostingPage:
    """The postings the user brought themselves, newest first, each with where
    reading and scoring it stands and its fit. Polled while one runs."""
    found = paginate(await deps.target.own_postings(user), paging.page, paging.page_size)
    return OwnPostingPage.of(found, OwnPosting.from_view)


@router.post("/own-postings", status_code=201)
async def add_own_posting(body: OwnPostingRequest, user: CurrentUser, deps: Deps) -> OwnPosting:
    """Store a role filled in by hand, privately. Spends nothing and queues
    nothing; it is read and scored when it is set as the target."""
    posting = await deps.target.add_own_posting(
        user,
        title=body.title,
        company_name=body.company_name,
        requirements=tuple(body.requirements),
    )
    return OwnPosting.from_view(posting)


@router.post("/own-postings/upload", status_code=201)
async def upload_own_posting(
    user: CurrentUser,
    deps: Deps,
    file: Annotated[UploadFile, File()],
    title: Annotated[str | None, Form(max_length=MAX_TITLE)] = None,
    company_name: Annotated[str | None, Form(max_length=MAX_COMPANY_NAME)] = None,
) -> OwnPosting:
    """Store an uploaded JD privately: a PDF, a Word file or plain text.
    Without a title it is named after its file until it is read. Spends
    nothing and queues nothing; the worker reads it when it is set as the
    target."""
    posting = await deps.target.upload_own_posting(
        user,
        title=title,
        company_name=company_name,
        filename=file.filename or "job description",
        content_type=file.content_type or "application/octet-stream",
        content=await file.read(),
    )
    return OwnPosting.from_view(posting)


@router.get("/own-postings/{private_job_posting_id}/target-estimate")
async def target_estimate(
    private_job_posting_id: uuid.UUID,
    user: CurrentUser,
    deps: Deps,
    with_questions: Annotated[bool, Query()] = False,
) -> OwnPostingEstimate:
    """What setting it as the target costs: nothing when its fit is current,
    otherwise reading what it asks for if that is not read yet, and scoring
    the fit. An unread file is priced as a ceiling. ``with_questions`` adds
    writing Fill the gap's questions, which follows (ADR 0042): priced as a
    ceiling until the posting is scored."""
    scoring = await deps.target.estimate_target(user, private_job_posting_id)
    if not with_questions:
        return OwnPostingEstimate.model_validate(scoring)
    if Decimal(scoring["cost_usd"]) == 0:
        ref = TargetRef(private_job_posting_id=str(private_job_posting_id))
        questions = await deps.gapfill.estimate_cost(user, ref)
    else:
        posting = await deps.target.own_posting(user, private_job_posting_id)
        questions = await deps.gapfill.estimate_ceiling(user, posting.title)
    return OwnPostingEstimate(
        cost_usd=str(Decimal(scoring["cost_usd"]) + Decimal(questions["cost_usd"])),
        model_id=scoring["model_id"] or questions["model_id"],
        rate_is_published=bool(scoring.get("rate_is_published", True))
        and bool(questions["rate_is_published"]),
    )


@router.post("/own-postings/{private_job_posting_id}/target", status_code=202)
async def set_as_target(
    private_job_posting_id: uuid.UUID,
    user: CurrentUser,
    deps: Deps,
    write_questions: Annotated[bool, Query()] = False,
) -> OwnPosting:
    """Make it ready to aim the Advisor at, at the cost the user confirmed:
    queue reading and scoring it, unless its fit is current or a run is
    already going. Poll ``GET /own-postings``. ``write_questions`` then writes
    Fill the gap's questions, once it is scored (ADR 0042)."""
    posting, evaluation_id = await deps.target.set_as_target(user, private_job_posting_id)
    questions_for = str(private_job_posting_id) if write_questions else None
    if evaluation_id is not None:
        await enqueue(
            "target.evaluate_own_posting",
            owner_id=str(user),
            evaluation_id=str(evaluation_id),
            then_write_questions_for=questions_for,
        )
    elif questions_for is not None and posting.status == "ready":
        await queue_questions(user, TargetRef(private_job_posting_id=questions_for))
    return OwnPosting.from_view(posting)


@router.post("/own-postings/{private_job_posting_id}/cancel", status_code=204)
async def cancel_evaluation(
    private_job_posting_id: uuid.UUID, user: CurrentUser, deps: Deps
) -> None:
    """Stops scoring it before its next call (ADR 0042). A call already sent
    is still charged."""
    await deps.target.cancel_evaluation(user, private_job_posting_id)


@router.delete("/own-postings/{private_job_posting_id}", status_code=204)
async def remove_own_posting(
    private_job_posting_id: uuid.UUID, user: CurrentUser, deps: Deps
) -> None:
    """Delete it, its JD and everything made of it. Plans and résumés aimed at
    it keep their snapshots."""
    await deps.target.remove_own_posting(user, private_job_posting_id)


__all__ = ["router"]
