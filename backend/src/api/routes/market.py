"""Market HTTP surface: watched roles at companies, chosen markets and pasted JDs."""

from __future__ import annotations

import uuid

from fastapi import APIRouter

from api.dependencies import CurrentUser, Deps, Paging
from api.schemas.common import Accepted, StringPage
from api.schemas.market import (
    JobDescriptionRequest,
    MarketRequest,
    PastedJobDescription,
    PastedJobDescriptionPage,
    Subscription,
    SubscriptionPage,
    SubscriptionRequest,
)
from kernel.paging import paginate
from wiring.queue import enqueue

router = APIRouter(tags=["market"])


@router.get("/role-subscriptions")
async def list_subscriptions(user: CurrentUser, deps: Deps, paging: Paging) -> SubscriptionPage:
    """Watched roles, newest first."""
    # Paged here, not in the service: the crawl fan-out and the Target picker
    # read the subscriptions whole.
    found = paginate(await deps.market.subscriptions(user), paging.page, paging.page_size)
    return SubscriptionPage.of(found, Subscription.from_view)


@router.post("/role-subscriptions", status_code=201)
async def subscribe(body: SubscriptionRequest, user: CurrentUser, deps: Deps) -> Subscription:
    subscription = await deps.market.subscribe(
        user,
        company_name=body.company_name,
        role_title=body.role_title,
        role_id=body.role_id,
        url=body.url,
    )
    await enqueue(
        "market.discover_board",
        owner_id=str(user),
        company_id=str(subscription.company_id),
        company_name=subscription.company_name,
        url=subscription.url,
    )
    return Subscription.from_view(subscription)


@router.delete("/role-subscriptions/{subscription_id}", status_code=204)
async def unsubscribe(subscription_id: uuid.UUID, user: CurrentUser, deps: Deps) -> None:
    await deps.market.unsubscribe(user, subscription_id)


@router.post("/role-subscriptions/{subscription_id}/refresh", status_code=202)
async def refresh(subscription_id: uuid.UUID, user: CurrentUser, deps: Deps) -> Accepted:
    """Re-crawl the company behind this subscription now. Rate limited; weekly
    stays the norm."""
    subscription = await deps.market.subscription(user, subscription_id)
    await deps.market.request_manual_refresh(user, subscription.company_id)
    await enqueue(
        "market.refresh_company", owner_id=str(user), company_id=str(subscription.company_id)
    )
    return Accepted()


@router.get("/market-preferences")
async def list_markets(user: CurrentUser, deps: Deps, paging: Paging) -> StringPage:
    """The markets the user chose. Adding or removing one answers with the
    whole saved set instead, since that is the result of the change."""
    found = paginate(await deps.market.markets(user), paging.page, paging.page_size)
    return StringPage.of(found, str)


@router.post("/market-preferences", status_code=201)
async def add_market(body: MarketRequest, user: CurrentUser, deps: Deps) -> list[str]:
    return await deps.market.add_market(user, body.market)


@router.delete("/market-preferences/{market}")
async def remove_market(market: str, user: CurrentUser, deps: Deps) -> list[str]:
    return await deps.market.remove_market(user, market)


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
