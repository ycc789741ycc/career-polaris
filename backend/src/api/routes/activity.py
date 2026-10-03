"""Activity HTTP surface: what background work is running (ADR 0018)."""

from __future__ import annotations

from fastapi import APIRouter

from api.dependencies import CurrentUser, Deps
from api.schemas.activity import Activity

router = APIRouter(tags=["activity"])


@router.get("/activity")
async def activity(user: CurrentUser, deps: Deps) -> Activity:
    """Syncs and parses still running, the newest analysis and role-map build,
    and the Advisor's jobs still running. The shell polls this while any of it
    is busy.

    ``activity`` sits beside ``gapplan`` and ``resume`` and cannot read them,
    so the Advisor's jobs are gathered here, from each component's public API
    (ADR 0042)."""
    advisor_jobs = (
        *await deps.gapfill.running_jobs(user),
        *await deps.gapplan.running_jobs(user),
        *await deps.resume.running_jobs(user),
        *await deps.target.running_jobs(user),
    )
    return Activity.from_view(await deps.activity.status(user), advisor_jobs)


__all__ = ["router"]
