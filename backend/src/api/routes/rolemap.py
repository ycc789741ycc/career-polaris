"""Role map HTTP surface: the bubble chart's roles, and the ones the user adds."""

from __future__ import annotations

import uuid

from fastapi import APIRouter

from advisor.rolemap import BuildRunView
from api.dependencies import CurrentUser, Deps, Paging
from api.schemas.activity import RunStatus
from api.schemas.rolemap import (
    CustomRoleEstimate,
    CustomRoleRequest,
    Role,
    RoleMapEstimate,
    RolePage,
)
from kernel.paging import paginate
from wiring.container import Container
from wiring.queue import enqueue

router = APIRouter(tags=["rolemap"])


@router.get("/roles")
async def list_roles(user: CurrentUser, deps: Deps, paging: Paging) -> RolePage:
    """The analysed roles: the ten recommended ones at most (ADR 0020)."""
    # Paged here, not in the service: other components read the roles whole.
    found = paginate(await deps.rolemap.roles(user), paging.page, paging.page_size)
    return RolePage.of(found, Role.from_view)


@router.get("/roles/cost-estimate")
async def cost_estimate(user: CurrentUser, deps: Deps) -> RoleMapEstimate:
    """Shown before a rebuild runs, so nothing is spent unasked."""
    return RoleMapEstimate.model_validate(await deps.rolemap.estimate_cost(user))


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
    return CustomRoleEstimate.model_validate(
        await deps.rolemap.estimate_custom_role(
            user,
            title=body.title,
            company_name=body.company_name,
            job_description=body.job_description,
        )
    )


@router.post("/roles/custom", status_code=201)
async def add_custom_role(body: CustomRoleRequest, user: CurrentUser, deps: Deps) -> Role:
    """Place a role the user named beside the ten (ADR 0021). Its JD, if any,
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


async def _request_build(user: uuid.UUID, deps: Container) -> BuildRunView:
    requested = await deps.activity.request_role_map(user)
    if requested.should_queue:
        await enqueue("rolemap.recluster", owner_id=str(user), build_id=str(requested.build.id))
    return requested.build


__all__ = ["router"]
