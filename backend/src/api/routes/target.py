"""Target HTTP surface: the postings the user brings themselves to aim the
Advisor at (Phase 8, ADR 0033), which are never on the role map."""

from __future__ import annotations

import uuid

from fastapi import APIRouter

from api.dependencies import CurrentUser, Deps, Paging
from api.schemas.target import OwnPosting, OwnPostingEstimate, OwnPostingPage, OwnPostingRequest
from kernel.paging import paginate
from wiring.queue import enqueue

router = APIRouter(tags=["target"])


@router.get("/own-postings")
async def own_postings(user: CurrentUser, deps: Deps, paging: Paging) -> OwnPostingPage:
    """The postings the user brought themselves, newest first, each with where
    reading and scoring it stands and its fit. Polled while one runs."""
    found = paginate(await deps.target.own_postings(user), paging.page, paging.page_size)
    return OwnPostingPage.of(found, OwnPosting.from_view)


@router.post("/own-postings/cost-estimate")
async def own_posting_estimate(
    body: OwnPostingRequest, user: CurrentUser, deps: Deps
) -> OwnPostingEstimate:
    """Priced before "Aim at it", so nothing is spent unasked: reading the JD's
    requirements, then scoring the fit. A POST, because a pasted JD does not
    fit in a query string."""
    return OwnPostingEstimate.model_validate(
        await deps.target.estimate_own_posting(
            user,
            title=body.title,
            company_name=body.company_name,
            job_description=body.job_description,
        )
    )


@router.post("/own-postings", status_code=202)
async def add_own_posting(body: OwnPostingRequest, user: CurrentUser, deps: Deps) -> OwnPosting:
    """Store the JD privately and queue reading and scoring it; poll
    ``GET /own-postings``. Never placed on the role map, and builds nothing."""
    posting, evaluation_id = await deps.target.add_own_posting(
        user,
        title=body.title,
        company_name=body.company_name,
        job_description=body.job_description,
    )
    await enqueue(
        "target.evaluate_own_posting", owner_id=str(user), evaluation_id=str(evaluation_id)
    )
    return OwnPosting.from_view(posting)


@router.get("/own-postings/{private_job_posting_id}/rescore-estimate")
async def rescore_estimate(
    private_job_posting_id: uuid.UUID, user: CurrentUser, deps: Deps
) -> OwnPostingEstimate:
    """What scoring it again against the latest strengths costs: the fit only."""
    return OwnPostingEstimate.model_validate(
        await deps.target.estimate_rescore(user, private_job_posting_id)
    )


@router.post("/own-postings/{private_job_posting_id}/rescore", status_code=202)
async def rescore(private_job_posting_id: uuid.UUID, user: CurrentUser, deps: Deps) -> OwnPosting:
    """Score it again against the latest strengths, at the cost the user
    confirmed. Asking while a run is going returns that one."""
    posting, evaluation_id = await deps.target.rescore_own_posting(user, private_job_posting_id)
    if evaluation_id is not None:
        await enqueue(
            "target.evaluate_own_posting", owner_id=str(user), evaluation_id=str(evaluation_id)
        )
    return OwnPosting.from_view(posting)


@router.delete("/own-postings/{private_job_posting_id}", status_code=204)
async def remove_own_posting(
    private_job_posting_id: uuid.UUID, user: CurrentUser, deps: Deps
) -> None:
    """Delete it, its JD and everything made of it. Plans and résumés aimed at
    it keep their snapshots."""
    await deps.target.remove_own_posting(user, private_job_posting_id)


__all__ = ["router"]
