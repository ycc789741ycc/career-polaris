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


__all__ = ["discover_board"]
