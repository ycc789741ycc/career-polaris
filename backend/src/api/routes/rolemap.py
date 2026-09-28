"""Role map HTTP surface: the bubble chart's roles."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from advisor.rolemap import MAX_ROLE_COUNT, MIN_ROLE_COUNT
from api.dependencies import CurrentUser, Deps
from api.schemas.common import Accepted
from api.schemas.rolemap import Role, RoleMapEstimate, RoleMapSettings
from wiring.queue import enqueue

router = APIRouter(tags=["rolemap"])


@router.get("/roles")
async def list_roles(user: CurrentUser, deps: Deps) -> list[Role]:
    return [Role.from_view(role) for role in await deps.rolemap.roles(user)]


@router.get("/roles/settings")
async def get_settings(user: CurrentUser, deps: Deps) -> RoleMapSettings:
    return RoleMapSettings(role_count=await deps.rolemap.role_count(user))


@router.put("/roles/settings")
async def put_settings(body: RoleMapSettings, user: CurrentUser, deps: Deps) -> RoleMapSettings:
    """Saved only after the user confirmed the estimate for this k, so a change
    queues a recluster through ``RoleCountChanged``."""
    return RoleMapSettings(role_count=await deps.rolemap.set_role_count(user, body.role_count))


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
async def recluster(user: CurrentUser, deps: Deps) -> Accepted:
    await enqueue("rolemap.recluster", owner_id=str(user))
    return Accepted()


__all__ = ["router"]
