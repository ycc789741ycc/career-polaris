"""Role map HTTP surface: the bubble chart's roles."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from advisor.rolemap import MAX_ROLE_COUNT, MIN_ROLE_COUNT, BuildRunView
from api.dependencies import CurrentUser, Deps, Paging
from api.schemas.activity import RunStatus
from api.schemas.rolemap import Role, RoleMapEstimate, RoleMapSettings, RolePage
from kernel.paging import paginate
from wiring.container import Container
from wiring.queue import enqueue

router = APIRouter(tags=["rolemap"])


@router.get("/roles")
async def list_roles(user: CurrentUser, deps: Deps, paging: Paging) -> RolePage:
    """The analysed roles: at most the user's k (ADR 0003)."""
    # Paged here, not in the service: other components read the roles whole.
    found = paginate(await deps.rolemap.roles(user), paging.page, paging.page_size)
    return RolePage.of(found, Role.from_view)


@router.get("/roles/settings")
async def get_settings(user: CurrentUser, deps: Deps) -> RoleMapSettings:
    return RoleMapSettings(role_count=await deps.rolemap.role_count(user))


@router.put("/roles/settings")
async def put_settings(body: RoleMapSettings, user: CurrentUser, deps: Deps) -> RoleMapSettings:
    """Saved only after the user confirmed the estimate for this k, so a change
    rebuilds the role map, waiting for an analysis that is running (ADR 0018).

    The build is recorded here rather than from ``RoleCountChanged``, so the
    page sees it the moment this returns."""
    previous = await deps.rolemap.role_count(user)
    saved = await deps.rolemap.set_role_count(user, body.role_count)
    if saved != previous:
        await _request_build(user, deps)
    return RoleMapSettings(role_count=saved)


@router.get("/roles/cost-estimate")
async def cost_estimate(
    user: CurrentUser,
    deps: Deps,
    role_count: Annotated[int | None, Query(ge=MIN_ROLE_COUNT, le=MAX_ROLE_COUNT)] = None,
) -> RoleMapEstimate:
    """Shown before a role map runs, so nothing is spent unasked. Pass
    ``role_count`` to price a k before saving it; omit it for the saved k."""
    return RoleMapEstimate.model_validate(
        await deps.rolemap.estimate_cost(user, role_count=role_count)
    )


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
