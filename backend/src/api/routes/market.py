"""Market HTTP surface: target locations and pasted JDs."""

from __future__ import annotations

from fastapi import APIRouter

from api.dependencies import CurrentUser, Deps, Paging
from api.schemas.common import StringPage
from api.schemas.market import (
    JobDescriptionRequest,
    MarketScope,
    PastedJobDescription,
    PastedJobDescriptionPage,
    TargetLocationsRequest,
)
from kernel.paging import paginate

router = APIRouter(tags=["market"])


@router.get("/target-locations")
async def list_target_locations(user: CurrentUser, deps: Deps, paging: Paging) -> StringPage:
    """Where the user wants to work: at most three places (domain decision 21)."""
    found = paginate(await deps.market.target_locations(user), paging.page, paging.page_size)
    return StringPage.of(found, str)


@router.put("/target-locations")
async def set_target_locations(
    body: TargetLocationsRequest, user: CurrentUser, deps: Deps
) -> list[str]:
    """Replace the whole set. A change rebuilds a role map the user already
    has, on the new scope; the worker does that from the event it records."""
    return await deps.market.set_target_locations(user, body.locations)


@router.get("/market-scope")
async def market_scope(user: CurrentUser, deps: Deps) -> MarketScope:
    return MarketScope.from_view(await deps.market.scope(user))


@router.get("/job-descriptions")
async def list_pasted(user: CurrentUser, deps: Deps, paging: Paging) -> PastedJobDescriptionPage:
    """The user's pasted JDs, newest first."""
    found = paginate(await deps.market.private_postings(user), paging.page, paging.page_size)
    return PastedJobDescriptionPage.of(found, PastedJobDescription.from_view)


@router.post("/job-descriptions", status_code=201)
async def paste(body: JobDescriptionRequest, user: CurrentUser, deps: Deps) -> PastedJobDescription:
    """A pasted JD is private to its owner and never enters shared data."""
    posting = await deps.market.paste_job_description(
        user,
        company_name=body.company_name,
        title=body.title,
        location=body.location,
        description=body.description,
        url=body.url,
    )
    return PastedJobDescription.from_view(posting)


__all__ = ["router"]
