"""Activity HTTP surface: what background work is running (ADR 0018)."""

from __future__ import annotations

from fastapi import APIRouter

from api.dependencies import CurrentUser, Deps
from api.schemas.activity import Activity

router = APIRouter(tags=["activity"])


@router.get("/activity")
async def activity(user: CurrentUser, deps: Deps) -> Activity:
    """Syncs and parses still running, and the newest analysis and role-map
    build. The shell polls this while any of it is busy."""
    return Activity.from_view(await deps.activity.status(user))


__all__ = ["router"]
