"""Role map HTTP surface: the bubble chart's roles and their fits, the
openings inside them, the candidates they come from, and the postings the user
brings themselves to aim the Advisor at (Phase 8), which are never on the
map."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Query

from advisor.rolemap import BuildRunView
from api.dependencies import CurrentUser, Deps, Paging
from api.schemas.activity import RunStatus
from api.schemas.common import Accepted
from api.schemas.rolemap import (
    Fit,
    FitPage,
    MatchedPosting,
    MatchedPostingPage,
    OwnPosting,
    OwnPostingEstimate,
    OwnPostingPage,
    OwnPostingRequest,
    Role,
    RoleCandidate,
    RoleCandidatePage,
    RoleMapEstimate,
    RoleMapState,
    RolePage,
)
from kernel.paging import paginate
from wiring.container import Container
from wiring.queue import enqueue, queue_build

router = APIRouter(tags=["rolemap"])


@router.get("/roles")
async def list_roles(user: CurrentUser, deps: Deps, paging: Paging) -> RolePage:
    """The analysed roles: the top k recommended ones at most (ADR 0029)."""
    # Paged here, not in the service: other components read the roles whole.
    # Counted live, so a bubble's openings are the ones Top matched can list.
    found = paginate(await deps.rolemap.map_roles(user), paging.page, paging.page_size)
    return RolePage.of(found, Role.from_view)


@router.get("/role-map")
async def role_map_state(user: CurrentUser, deps: Deps) -> RoleMapState:
    """How current the map is: the market it was built from, and whether the
    target locations changed since (ADR 0027)."""
    built = await deps.rolemap.last_finished_build(user)
    if built is None or not built.needed_source_ids:
        # No map yet, or one built before builds recorded what they read.
        return RoleMapState(market_data_at=None, built_for_locations=None, locations_changed=False)
    current = await deps.market.target_locations(user)
    return RoleMapState(
        market_data_at=built.market_data_at,
        built_for_locations=list(built.locations),
        locations_changed=sorted(built.locations) != sorted(current),
    )


@router.get("/role-candidates")
async def list_candidates(user: CurrentUser, deps: Deps, paging: Paging) -> RoleCandidatePage:
    """The roles the latest analysis recommended, best fit first, each with the
    role it became or none when the market lacks it (ADR 0024)."""
    found = paginate(await deps.rolemap.candidates(user), paging.page, paging.page_size)
    return RoleCandidatePage.of(found, RoleCandidate.from_view)


@router.get("/roles/cost-estimate")
async def cost_estimate(user: CurrentUser, deps: Deps) -> RoleMapEstimate:
    """Shown before a rebuild runs, so nothing is spent unasked: the build, and
    the fits scored once it ends."""
    estimate = await deps.rolemap.estimate_cost(user)
    fits = await deps.rolemap.estimate_fits(user, recommended=estimate["max_roles"])
    return RoleMapEstimate.model_validate(_with_fits(estimate, fits))


@router.post("/roles/recluster", status_code=202)
async def recluster(user: CurrentUser, deps: Deps) -> RunStatus:
    """Record a rebuild. ``running`` when it was queued now, ``waiting`` when an
    analysis is running and it starts after (ADR 0018). Asking while one is
    already under way returns that one."""
    return RunStatus.from_build(await _request_build(user, deps))


@router.get("/own-postings")
async def own_postings(user: CurrentUser, deps: Deps, paging: Paging) -> OwnPostingPage:
    """The postings the user brought themselves, newest first, each with where
    reading and scoring it stands and its fit. Polled while one runs."""
    found = paginate(await deps.rolemap.own_postings(user), paging.page, paging.page_size)
    return OwnPostingPage.of(found, OwnPosting.from_view)


@router.post("/own-postings/cost-estimate")
async def own_posting_estimate(
    body: OwnPostingRequest, user: CurrentUser, deps: Deps
) -> OwnPostingEstimate:
    """Priced before "Aim at it", so nothing is spent unasked: reading the JD's
    requirements, then scoring the fit. A POST, because a pasted JD does not
    fit in a query string."""
    return OwnPostingEstimate.model_validate(
        await deps.rolemap.estimate_own_posting(
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
    posting, evaluation_id = await deps.rolemap.add_own_posting(
        user,
        title=body.title,
        company_name=body.company_name,
        job_description=body.job_description,
    )
    await enqueue(
        "rolemap.evaluate_own_posting", owner_id=str(user), evaluation_id=str(evaluation_id)
    )
    return OwnPosting.from_view(posting)


@router.get("/own-postings/{private_job_posting_id}/rescore-estimate")
async def rescore_estimate(
    private_job_posting_id: uuid.UUID, user: CurrentUser, deps: Deps
) -> OwnPostingEstimate:
    """What scoring it again against the latest strengths costs: the fit only."""
    return OwnPostingEstimate.model_validate(
        await deps.rolemap.estimate_rescore(user, private_job_posting_id)
    )


@router.post("/own-postings/{private_job_posting_id}/rescore", status_code=202)
async def rescore(private_job_posting_id: uuid.UUID, user: CurrentUser, deps: Deps) -> OwnPosting:
    """Score it again against the latest strengths, at the cost the user
    confirmed. Asking while a run is going returns that one."""
    posting, evaluation_id = await deps.rolemap.rescore_own_posting(user, private_job_posting_id)
    if evaluation_id is not None:
        await enqueue(
            "rolemap.evaluate_own_posting", owner_id=str(user), evaluation_id=str(evaluation_id)
        )
    return OwnPosting.from_view(posting)


@router.delete("/own-postings/{private_job_posting_id}", status_code=204)
async def remove_own_posting(
    private_job_posting_id: uuid.UUID, user: CurrentUser, deps: Deps
) -> None:
    """Delete it, its JD with it. Plans and résumés aimed at it keep their
    snapshots."""
    await deps.rolemap.remove_own_posting(user, private_job_posting_id)


def _with_fits(estimate: dict[str, Any], fits: dict[str, Any]) -> dict[str, Any]:
    """A build's price with the fits it is scored with added in (ADR 0024)."""
    return {
        **estimate,
        "cost_usd": str(Decimal(estimate["cost_usd"]) + Decimal(fits["cost_usd"])),
        "fits_cost_usd": fits["cost_usd"],
        "rate_is_published": estimate.get("rate_is_published") is not False
        and fits["rate_is_published"],
    }


@router.get("/fits")
async def fits(user: CurrentUser, deps: Deps, paging: Paging) -> FitPage:
    """Bubble sizes. Fit belongs to the User x Role pair, never to the role."""
    # Paged here, not in the service: other components read the fits whole.
    found = paginate(await deps.rolemap.fits(user), paging.page, paging.page_size)
    return FitPage.of(found, Fit.from_view)


@router.get("/matched-postings")
async def matched_postings(
    user: CurrentUser,
    deps: Deps,
    paging: Paging,
    role_id: Annotated[uuid.UUID | None, Query()] = None,
) -> MatchedPostingPage:
    """The openings inside the user's roles, best first, for the role map's "Top
    matched" list: ask for ``page_size=10`` for the top ten. Across all roles
    it holds one opening per company, the best-ranked one. ``role_id`` keeps
    one role's, every opening the Advisor can aim at in it. Ranked by the
    role's fit; no AI runs to produce it."""
    ranked = await deps.rolemap.matched_postings(user, limit=None, role_id=role_id)
    return MatchedPostingPage.of(
        paginate(ranked, paging.page, paging.page_size), MatchedPosting.from_view
    )


@router.post("/fits/compute", status_code=202)
async def compute_fits(user: CurrentUser, deps: Deps) -> Accepted:
    await enqueue("rolemap.compute_fits", owner_id=str(user))
    return Accepted()


async def _request_build(user: uuid.UUID, deps: Container) -> BuildRunView:
    requested = await deps.activity.request_role_map(user)
    await queue_build(user, requested)
    return requested.build


__all__ = ["router"]
