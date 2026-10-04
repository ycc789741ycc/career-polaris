"""The ``crawler`` deployable.

Its own process on purpose: it parses hostile HTML from the internet, it runs
on its own loop, and it holds no secrets and reads no user data. Its database
connection uses the ``crawler_rw`` role, which has no grant on any user schema
— a mistake here fails at the database rather than leaking.

It fetches only what a role-map build is waiting for (ADR 0027): every
``CRAWL_DUE_POLL_SECONDS`` it reads the due sources, which is one query, and
crawls only when there are some. Once a day it retires the searches no build
needs any more and thins the postings nothing holds.
"""

from __future__ import annotations

import asyncio
import time
from datetime import timedelta

from advisor.market import CrawlIngest, CrawlPoliteness, crawl_due, create_crawl_politeness
from kernel.clock import utcnow
from kernel.config import Settings, Unit, get_settings
from kernel.db import get_psycopg_dsn
from kernel.logging import configure_logging, get_logger
from kernel.presence import Heartbeat
from wiring.crawl import build_crawl_ingest

log = get_logger(__name__)

SWEEP_SECONDS = 24 * 60 * 60


async def crawl_once(ingest: CrawlIngest, politeness: CrawlPoliteness, settings: Settings) -> None:
    """Fetch whatever builds are waiting for, and nothing else."""
    outcomes = await crawl_due(
        ingest,
        politeness,
        user_agent=settings.crawl_user_agent,
        timeout_seconds=settings.crawl_http_timeout_seconds,
        embedding_model=settings.embedding_model_name,
    )
    if outcomes:
        log.info(
            "crawl.due_sources_completed",
            sources=len(outcomes),
            failed=sum(1 for o in outcomes if o.error),
            upserted=sum(o.upserted for o in outcomes),
            expired=sum(o.expired for o in outcomes),
        )


async def sweep(ingest: CrawlIngest, settings: Settings) -> None:
    """Let what nobody asks for stop taking room (ADR 0027)."""
    now = utcnow()
    retired = await ingest.retire_idle_searches(
        idle_since=now - timedelta(days=settings.market_source_idle_days)
    )
    thinned = await ingest.thin_unheld_postings(
        unseen_since=now - timedelta(days=settings.posting_thin_after_days)
    )
    log.info("crawl.swept", searches_retired=retired, postings_thinned=thinned)


async def main() -> None:
    settings = get_settings()
    configure_logging(f"{settings.service_name}-crawler", settings.log_level)
    # Missing configuration fails here, at startup, not at first use.
    settings.require_for(Unit.CRAWLER)
    database, ingest = build_crawl_ingest(settings)
    politeness = create_crawl_politeness(
        user_agent=settings.crawl_user_agent,
        rate_limit_per_second=settings.crawl_rate_limit_per_host_per_second,
        max_requests_per_host_per_day=settings.crawl_max_requests_per_host_per_day,
    )
    # Says the crawler is up: a build waiting for the market counts its
    # deadline only while it is (ADR 0052).
    heartbeat = Heartbeat(
        get_psycopg_dsn(settings.require_crawler_database_url()),
        Unit.CRAWLER,
        interval_seconds=settings.presence_heartbeat_seconds,
    )
    heartbeat.start()
    next_sweep = time.monotonic()
    try:
        while True:
            try:
                if time.monotonic() >= next_sweep:
                    await sweep(ingest, settings)
                    next_sweep = time.monotonic() + SWEEP_SECONDS
                await crawl_once(ingest, politeness, settings)
            except Exception:
                # A failed look must not end the process; the next one tries
                # again, and the sources it missed are still due.
                log.error("crawl.loop_failed", exc_info=True)
            await asyncio.sleep(settings.crawl_due_poll_seconds)
    finally:
        heartbeat.stop()
        await database.dispose()


if __name__ == "__main__":
    asyncio.run(main())
