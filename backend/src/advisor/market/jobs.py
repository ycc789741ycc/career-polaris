"""Worker use cases for the market component."""

from __future__ import annotations

import uuid
from typing import Any

from kernel.fetch import GuardedClient
from kernel.logging import get_logger

log = get_logger(__name__)


async def discover_board(deps: Any, *, company_id: str, company_name: str) -> None:
    """Look for a supported job board for a company, and crawl it as a
    ``demand`` source with no owner if one is found.

    Nothing about who named the company reaches here, so the source it leaves
    behind cannot say either. A company with a source already is left alone.
    """
    from advisor.market.crawling.discovery import discover_board as probe

    name = await deps.market.company_needing_source(uuid.UUID(company_id), company_name)
    if name is None:
        return
    settings = deps.settings
    async with GuardedClient(
        timeout_seconds=settings.crawl_http_timeout_seconds,
        user_agent=settings.crawl_user_agent,
    ) as client:
        found = await probe(client, name, user_agent=settings.crawl_user_agent)

    if found is not None:
        await deps.market.register_board(
            uuid.UUID(company_id), kind=found.adapter_name, endpoint=found.endpoint
        )
    log.info("market.board_discovered", company=name, found=found is not None)


async def request_searches(deps: Any, *, titles: list[str], locations: list[str]) -> None:
    """Make sure a public job API is searched for each title in each place
    (ADR 0025), as ``demand`` sources with no owner.

    Only titles and places reach here. A place a search cannot be scoped to —
    a city, a region — adds none: its postings come from company boards. The
    crawler reads a new search within minutes, and its postings then rebuild
    the role maps of whoever wants to work there.
    """
    from advisor.market.crawling.adapters import SEARCH_ADAPTERS
    from advisor.market.domain import search_scope

    scopes = {scope for place in locations if (scope := search_scope(place)) is not None}
    created = 0
    for adapter in SEARCH_ADAPTERS:
        searches: dict[str, str] = {}
        for scope in scopes:
            for title in titles:
                endpoint = adapter.search_endpoint(title, scope)
                if endpoint is not None:
                    searches[endpoint] = scope.label
        if searches:
            created += await deps.market.request_searches(kind=adapter.name, searches=searches)
    log.info(
        "market.searches_requested",
        titles=len(titles),
        places=len(scopes),
        new_sources=created,
    )


__all__ = ["discover_board", "request_searches"]
