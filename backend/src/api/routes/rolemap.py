"""Role map HTTP surface: the bubble chart's roles."""

from __future__ import annotations

import uuid

from fastapi import APIRouter

from advisor.rolemap import BuildRunView
from api.dependencies import CurrentUser, Deps, Paging
from api.schemas.activity import RunStatus
from api.schemas.rolemap import Role, RoleMapEstimate, RolePage
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


async def _request_build(user: uuid.UUID, deps: Container) -> BuildRunView:
    requested = await deps.activity.request_role_map(user)
    if requested.should_queue:
        await enqueue("rolemap.recluster", owner_id=str(user), build_id=str(requested.build.id))
    return requested.build


__all__ = ["router"]
