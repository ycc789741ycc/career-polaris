"""Builds the market component from the infrastructure handles it is given.

The composition root calls these; nothing else constructs a repository or a
unit of work (ADR 0011).
"""

from __future__ import annotations

from advisor.market.crawling.politeness import HostGuard, RateLimiter, RobotsCache
from advisor.market.crawling.run import CrawlPoliteness
from advisor.market.infra.unit_of_work import SqlAlchemyMarketUnitOfWork
from advisor.market.service import CrawlIngest, FreshWindows, MarketService
from kernel.clock import utcnow
from kernel.db import Database


def create_market_service(database: Database, *, windows: FreshWindows) -> MarketService:
    """``windows``: how long a fetch is reused before a build asks again."""
    return MarketService(SqlAlchemyMarketUnitOfWork(database), windows=windows)


def create_crawl_ingest(database: Database) -> CrawlIngest:
    """The crawler's view of the market: pass it the crawler role's database."""
    return CrawlIngest(SqlAlchemyMarketUnitOfWork(database))


def create_crawl_politeness(
    *, user_agent: str, rate_limit_per_second: float, max_requests_per_host_per_day: int
) -> CrawlPoliteness:
    """What the crawler keeps between its looks for due sources: robots.txt,
    the per-host rate, and each host's pause and daily count (ADR 0027)."""
    return CrawlPoliteness(
        robots=RobotsCache(user_agent),
        limiter=RateLimiter(per_second=rate_limit_per_second),
        guard=HostGuard(max_per_day=max_requests_per_host_per_day, clock=utcnow),
    )
