"""Role map HTTP surface: the bubble chart's roles and their fits, the
openings inside them, the candidates they come from, and the ones the user
adds."""

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
    CustomRoleEstimate,
    CustomRoleRequest,
    Fit,
    FitPage,
    MatchedPosting,
    MatchedPostingPage,
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
    """The analysed roles: the top k recommended ones at most (ADR 0029), and
    the user's own."""
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


@router.post("/roles/custom/cost-estimate")
async def custom_role_estimate(
    body: CustomRoleRequest, user: CurrentUser, deps: Deps
) -> CustomRoleEstimate:
    """Priced before "Add to Role Map", so nothing is spent unasked. A POST,
    because a pasted JD does not fit in a query string."""
    estimate = await deps.rolemap.estimate_custom_role(
        user,
        title=body.title,
        company_name=body.company_name,
        job_description=body.job_description,
    )
    # The build that places it scores every role's fit, this one's included.
    fits = await deps.rolemap.estimate_fits(user, extra_roles=1)
    return CustomRoleEstimate.model_validate(_with_fits(estimate, fits))


@router.post("/roles/custom", status_code=201)
async def add_custom_role(body: CustomRoleRequest, user: CurrentUser, deps: Deps) -> Role:
    """Place a role the user named beside the top k (ADR 0021). Its JD, if any,
    is stored privately; the build that analyses it is recorded here, so the
    page sees it at once, and waits for a running analysis (ADR 0018)."""
    jd = (body.job_description or "").strip()
    private_posting_id = None
    if jd:
        pasted = await deps.market.paste_job_description(
            user,
            company_name=body.company_name or "",
            title=body.title,
            location=None,
            description=jd,
        )
        private_posting_id = pasted.id
    role = await deps.rolemap.add_custom_role(
        user,
        title=body.title,
        company_name=body.company_name,
        private_posting_id=private_posting_id,
    )
    await _request_build(user, deps)
    return Role.from_view(role)


@router.delete("/roles/custom/{role_id}", status_code=204)
async def remove_custom_role(role_id: uuid.UUID, user: CurrentUser, deps: Deps) -> None:
    await deps.rolemap.remove_custom_role(user, role_id)


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
