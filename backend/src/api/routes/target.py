"""Target HTTP surface: what a plan or a résumé can be aimed at."""

from __future__ import annotations

from fastapi import APIRouter

from api.dependencies import CurrentUser, Deps
from api.schemas.target import TargetOption

router = APIRouter(tags=["target"])


@router.get("/targets")
async def list_targets(user: CurrentUser, deps: Deps) -> list[TargetOption]:
    """Matched openings, then watched roles, then pasted JDs. No AI runs."""
    return [TargetOption.from_view(option) for option in await deps.target.options(user)]
