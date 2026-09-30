"""One crawl run.

Fetch each due source, normalise, dedup, expire what has gone, then embed.
The crawler never works out which users are affected — that would need user
data it has no grant on. It emits events about markets and companies, and the
worker fans them out (docs/architecture.md section 2).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from advisor.market.crawling.adapters import SOURCES
from advisor.market.crawling.politeness import RateLimiter, RobotsCache, origin_of, robots_url_for
from advisor.market.service import CrawlIngest, CrawlSourceView, NormalizedPosting
from kernel.embeddings import embed
from kernel.errors import BlockedAddressError, UpstreamFailedError
from kernel.fetch import GuardedClient
from kernel.logging import get_logger

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class CrawlOutcome:
    source_id: uuid.UUID
    upserted: int
    expired: int
    error: str | None
    # A search's place, when an opening there appeared or went: announced once
    # per place after the run, not once per search (ADR 0025).
    changed_market: str | None = None


async def fetch_source(
    client: GuardedClient,
    source: CrawlSourceView,
    *,
    robots: RobotsCache,
    limiter: RateLimiter,
) -> list[NormalizedPosting]:
    adapter = SOURCES.get(source.kind)
    if adapter is None:
        raise UpstreamFailedError(f"no adapter for source kind {source.kind!r}")

    origin = origin_of(source.endpoint)
    if not robots.knows(origin):
        try:
            await limiter.wait(source.endpoint)
            response = await client.request("GET", robots_url_for(source.endpoint))
            robots.remember(origin, response.text if response.status_code == 200 else None)
        except (UpstreamFailedError, BlockedAddressError):
            robots.remember(origin, None)

    if not robots.allows(source.endpoint):
        raise UpstreamFailedError("robots.txt disallows this endpoint", endpoint=source.endpoint)

    await limiter.wait(source.endpoint)
    response = await client.request("GET", source.endpoint)
    if response.status_code >= 400:
        raise UpstreamFailedError(
            f"board returned {response.status_code}", endpoint=source.endpoint
        )

    company_name = source.company_name or "Unknown"
    payload = response.json() if _looks_like_json(response.text) else response.text
    return adapter.parse(payload, company_name=company_name)


async def crawl_one_source(
    ingest: CrawlIngest,
    source: CrawlSourceView,
    *,
    user_agent: str,
    timeout_seconds: float,
    rate_limit_per_second: float,
) -> CrawlOutcome:
    """One source, on demand — the rate-limited single-company refresh."""
    robots = RobotsCache(user_agent)
    limiter = RateLimiter(per_second=rate_limit_per_second)
    async with GuardedClient(timeout_seconds=timeout_seconds, user_agent=user_agent) as client:
        try:
            postings = await fetch_source(client, source, robots=robots, limiter=limiter)
        except (UpstreamFailedError, BlockedAddressError) as exc:
            await ingest.record_crawl(source.id, [], error=exc.message)
            return CrawlOutcome(source.id, 0, 0, exc.message)
    return await _store(ingest, source, postings)


async def crawl_all(
    ingest: CrawlIngest,
    *,
    user_agent: str,
    timeout_seconds: float,
    rate_limit_per_second: float,
    embedding_model: str,
) -> list[CrawlOutcome]:
    """The weekly run: every active source."""
    return await _crawl(
        ingest,
        await ingest.due_sources(),
        user_agent=user_agent,
        timeout_seconds=timeout_seconds,
        rate_limit_per_second=rate_limit_per_second,
        embedding_model=embedding_model,
    )


async def crawl_new(
    ingest: CrawlIngest,
    *,
    user_agent: str,
    timeout_seconds: float,
    rate_limit_per_second: float,
    embedding_model: str,
) -> list[CrawlOutcome]:
    """Between weekly runs: only the sources no crawl has fetched yet, so a
    search a user's candidates asked for is read within minutes (ADR 0025).
    A source that fails is marked fetched too, and waits for the weekly run."""
    sources = await ingest.new_sources()
    if not sources:
        return []
    return await _crawl(
        ingest,
        sources,
        user_agent=user_agent,
        timeout_seconds=timeout_seconds,
        rate_limit_per_second=rate_limit_per_second,
        embedding_model=embedding_model,
    )


async def _crawl(
    ingest: CrawlIngest,
    sources: list[CrawlSourceView],
    *,
    user_agent: str,
    timeout_seconds: float,
    rate_limit_per_second: float,
    embedding_model: str,
) -> list[CrawlOutcome]:
    robots = RobotsCache(user_agent)
    limiter = RateLimiter(per_second=rate_limit_per_second)
    outcomes: list[CrawlOutcome] = []

    async with GuardedClient(timeout_seconds=timeout_seconds, user_agent=user_agent) as client:
        for source in sources:
            try:
                postings = await fetch_source(client, source, robots=robots, limiter=limiter)
            except (UpstreamFailedError, BlockedAddressError) as exc:
                # One bad board must not stop the run; the source records why.
                # A host that no longer resolves, or now resolves somewhere
                # private, is a bad board too.
                log.warning("crawl.source_failed", source_id=str(source.id), reason=exc.message)
                await ingest.record_crawl(source.id, [], error=exc.message)
                outcomes.append(CrawlOutcome(source.id, 0, 0, exc.message))
                continue

            outcome = await _store(ingest, source, postings)
            outcomes.append(outcome)
            if outcome.error is None:
                log.info(
                    "crawl.source_done",
                    source_id=str(source.id),
                    upserted=outcome.upserted,
                    expired=outcome.expired,
                )

    await embed_new_postings(ingest, embedding_model)
    # After embedding, so the rebuild an announcement starts finds the vectors.
    changed = {o.changed_market for o in outcomes if o.changed_market}
    if changed:
        await ingest.announce_markets(changed)
    return outcomes


async def _store(
    ingest: CrawlIngest, source: CrawlSourceView, postings: list[NormalizedPosting]
) -> CrawlOutcome:
    """Store one source's postings. A source whose postings cannot be stored is
    recorded as failed, so one bad board costs its own run and not everyone's.

    A board announces its own change. A search of a place is stored quietly:
    a place has many searches, and each announcement is a role-map rebuild on
    somebody's key, so the run announces the place once."""
    changed_market: str | None = None
    try:
        if source.company_id is None and source.market:
            upserted, expired, changed = await ingest.record_search_crawl(source.id, postings)
            changed_market = source.market if changed else None
        else:
            upserted, expired = await ingest.record_crawl(source.id, postings)
    except Exception as exc:
        # The storing transaction rolled back as a whole; nothing half-written
        # remains. Record why on the source and let the run go on.
        reason = f"storing postings failed: {type(exc).__name__}"
        log.exception("crawl.source_store_failed", source_id=str(source.id), reason=reason)
        await ingest.record_crawl(source.id, [], error=reason)
        return CrawlOutcome(source.id, 0, 0, reason)
    return CrawlOutcome(source.id, upserted, expired, None, changed_market)


async def embed_new_postings(ingest: CrawlIngest, model_name: str, batch: int = 200) -> int:
    """Embed postings that have none yet. Platform-paid computation."""
    pending = await ingest.postings_needing_embeddings(model_name, limit=batch)
    if not pending:
        return 0
    vectors = embed([text for _id, text in pending], model_name=model_name)
    await ingest.store_embeddings(
        model_name,
        {posting_id: vector for (posting_id, _), vector in zip(pending, vectors, strict=True)},
    )
    return len(pending)


def _looks_like_json(text: str) -> bool:
    stripped = text.lstrip()
    return stripped.startswith(("{", "["))
