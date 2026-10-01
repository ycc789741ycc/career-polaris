"""The ``crawler`` deployable.

Its own process on purpose: it parses hostile HTML from the internet, it runs
on a different schedule, and it holds no secrets and reads no user data. Its
database connection uses the ``crawler_rw`` role, which has no grant on any
user schema — a mistake here fails at the database rather than leaking.
"""

from __future__ import annotations

import asyncio
import time

from advisor.market import crawl_all, crawl_new
from kernel.clock import utcnow
from kernel.config import Unit, get_settings
from kernel.logging import configure_logging, get_logger
from wiring.crawl import build_crawl_ingest

log = get_logger(__name__)

WEEKLY_SECONDS = 7 * 24 * 60 * 60
# How often, between weekly runs, to look for sources nothing has fetched yet:
# a search a user's candidates just asked for, or a board just discovered
# (ADR 0025). Reading that list is one query; a crawl happens only when it is
# not empty.
NEW_SOURCE_POLL_SECONDS = 120


async def run_once() -> None:
    settings = get_settings()
    database, ingest = build_crawl_ingest(settings)
    try:
        retired = await ingest.retire_idle_searches(utcnow())
        if retired:
            log.info("crawl.idle_searches_retired", sources=retired)
        outcomes = await crawl_all(
            ingest,
            user_agent=settings.crawl_user_agent,
            timeout_seconds=settings.crawl_http_timeout_seconds,
            rate_limit_per_second=settings.crawl_rate_limit_per_host_per_second,
            embedding_model=settings.embedding_model_name,
        )
        log.info(
            "crawl.completed",
            sources=len(outcomes),
            failed=sum(1 for o in outcomes if o.error),
            upserted=sum(o.upserted for o in outcomes),
            expired=sum(o.expired for o in outcomes),
        )
    finally:
        await database.dispose()


async def run_new() -> None:
    """Crawl whatever has appeared since the last look, and nothing else."""
    settings = get_settings()
    database, ingest = build_crawl_ingest(settings)
    try:
        outcomes = await crawl_new(
            ingest,
            user_agent=settings.crawl_user_agent,
            timeout_seconds=settings.crawl_http_timeout_seconds,
            rate_limit_per_second=settings.crawl_rate_limit_per_host_per_second,
            embedding_model=settings.embedding_model_name,
        )
        if outcomes:
            log.info(
                "crawl.new_sources_completed",
                sources=len(outcomes),
                failed=sum(1 for o in outcomes if o.error),
                upserted=sum(o.upserted for o in outcomes),
            )
    finally:
        await database.dispose()


async def main() -> None:
    settings = get_settings()
    configure_logging(f"{settings.service_name}-crawler", settings.log_level)
    # Missing configuration fails here, at startup, not at first use.
    settings.require_for(Unit.CRAWLER)
    # One weekly crawl covers company boards and searches; in between, only
    # sources that have never been fetched are crawled.
    while True:
        await run_once()
        next_weekly = time.monotonic() + WEEKLY_SECONDS
        while time.monotonic() < next_weekly:
            await asyncio.sleep(NEW_SOURCE_POLL_SECONDS)
            try:
                await run_new()
            except Exception:
                # A failed look must not end the process and with it the
                # weekly crawl; the next look tries again.
                log.error("crawl.new_sources_failed", exc_info=True)


if __name__ == "__main__":
    asyncio.run(main())
