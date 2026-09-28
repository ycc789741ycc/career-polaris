"""Target HTTP surface: what a plan or a résumé can be aimed at."""

from __future__ import annotations

from fastapi import APIRouter

from api.dependencies import CurrentUser, Deps, Paging
from api.schemas.target import TargetOption, TargetOptionPage
from kernel.paging import paginate

router = APIRouter(tags=["target"])


@router.get("/targets")
async def list_targets(user: CurrentUser, deps: Deps, paging: Paging) -> TargetOptionPage:
    """Matched openings, then watched roles, then pasted JDs. No AI runs."""
    # Merged from three components, so paged after the merge.
    found = paginate(await deps.target.options(user), paging.page, paging.page_size)
    return TargetOptionPage.of(found, TargetOption.from_view)
