"""One crawl run: the sources builds are waiting for.

Fetch each due source, normalise, dedup, store, embed, and only then mark it
fetched, so a build that starts on it finds the vectors (ADR 0027). The
crawler never works out which users are affected, and announces nothing: a
build that needs a source waits for it and reads it itself.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from advisor.market.crawling.adapters import SOURCES
from advisor.market.crawling.politeness import (
    HostGuard,
    RateLimiter,
    RobotsCache,
    host_of,
    origin_of,
    robots_url_for,
)
from advisor.market.service import CrawlIngest, CrawlSourceView, NormalizedPosting
from kernel.embeddings import embed
from kernel.errors import BlockedAddressError, RateLimitedError, UpstreamFailedError
from kernel.fetch import GuardedClient
from kernel.logging import get_logger

log = get_logger(__name__)

# A host that answers these is asking us to stop for a while, not failing.
_REFUSALS = frozenset({403, 429})


@dataclass(frozen=True, slots=True)
class CrawlOutcome:
    source_id: uuid.UUID
    upserted: int
    expired: int
    error: str | None


@dataclass
class CrawlPoliteness:
    """What the crawler keeps between runs: one per process (ADR 0027)."""

    robots: RobotsCache
    limiter: RateLimiter
    guard: HostGuard


async def fetch_source(
    client: GuardedClient,
    source: CrawlSourceView,
    *,
    robots: RobotsCache,
    limiter: RateLimiter,
    guard: HostGuard | None = None,
) -> list[NormalizedPosting]:
    """Fetch and parse one source. ``guard`` (the crawler's) raises
    ``RateLimitedError`` for a host that is paused or spent, and pauses one
    that refuses us."""
    adapter = SOURCES.get(source.kind)
    if adapter is None:
        raise UpstreamFailedError(f"no adapter for source kind {source.kind!r}")

    origin = origin_of(source.endpoint)
    if not robots.knows(origin):
        try:
            await _admit(robots_url_for(source.endpoint), limiter, guard)
            response = await client.request("GET", robots_url_for(source.endpoint))
            robots.remember(origin, response.text if response.status_code == 200 else None)
        except (UpstreamFailedError, BlockedAddressError):
            robots.remember(origin, None)

    if not robots.allows(source.endpoint):
        raise UpstreamFailedError("robots.txt disallows this endpoint", endpoint=source.endpoint)

    await _admit(source.endpoint, limiter, guard)
    response = await client.request("GET", source.endpoint)
    if response.status_code in _REFUSALS and guard is not None:
        until = guard.refused(source.endpoint, response.headers.get("retry-after"))
        raise RateLimitedError(
            f"host answered {response.status_code}",
            host=host_of(source.endpoint),
            until=until.isoformat(),
        )
    if response.status_code >= 400:
        raise UpstreamFailedError(
            f"board returned {response.status_code}", endpoint=source.endpoint
        )
    if guard is not None:
        guard.answered(source.endpoint)

    company_name = source.company_name or "Unknown"
    payload = response.json() if _looks_like_json(response.text) else response.text
    return adapter.parse(payload, company_name=company_name)


async def _admit(url: str, limiter: RateLimiter, guard: HostGuard | None) -> None:
    """Wait our turn for this host, and count the request against its day."""
    if guard is not None:
        guard.check(url)
        guard.count(url)
    await limiter.wait(url)


async def crawl_due(
    ingest: CrawlIngest,
    politeness: CrawlPoliteness,
    *,
    user_agent: str,
    timeout_seconds: float,
    embedding_model: str,
) -> list[CrawlOutcome]:
    """Fetch every source a build is waiting for (ADR 0027).

    A source on a host that is paused or past its daily ceiling is skipped and
    stays due. Any other failure is recorded on the source and counts as
    fetched, so the builds waiting for it go on without it.
    """
    sources = await ingest.due_sources()
    if not sources:
        return []
    outcomes: list[CrawlOutcome] = []
    fetched: list[uuid.UUID] = []
    async with GuardedClient(timeout_seconds=timeout_seconds, user_agent=user_agent) as client:
        for source in sources:
            try:
                postings = await fetch_source(
                    client,
                    source,
                    robots=politeness.robots,
                    limiter=politeness.limiter,
                    guard=politeness.guard,
                )
            except RateLimitedError as exc:
                # Not the source's fault: it stays due, and is tried again
                # once the host may be asked.
                log.warning(
                    "crawl.host_held_back",
                    source_id=str(source.id),
                    host=host_of(source.endpoint),
                    reason=exc.message,
                )
                continue
            except (UpstreamFailedError, BlockedAddressError) as exc:
                # One bad source must not stop the run; the source records why.
                # A host that no longer resolves, or now resolves somewhere
                # private, is a bad source too.
                log.warning("crawl.source_failed", source_id=str(source.id), reason=exc.message)
                await ingest.record_crawl(source.id, [], error=exc.message)
                outcomes.append(CrawlOutcome(source.id, 0, 0, exc.message))
                fetched.append(source.id)
                continue

            outcome = await _store(ingest, source, postings)
            outcomes.append(outcome)
            fetched.append(source.id)
            if outcome.error is None:
                log.info(
                    "crawl.source_done",
                    source_id=str(source.id),
                    upserted=outcome.upserted,
                    expired=outcome.expired,
                )

    await embed_new_postings(ingest, embedding_model)
    # Only now: a build that starts on these sources finds their vectors.
    await ingest.mark_fetched(fetched)
    return outcomes


async def _store(
    ingest: CrawlIngest, source: CrawlSourceView, postings: list[NormalizedPosting]
) -> CrawlOutcome:
    """Store one source's postings. A source whose postings cannot be stored is
    recorded as failed, so one bad board costs its own run and not everyone's."""
    try:
        upserted, expired = await ingest.record_crawl(source.id, postings)
    except Exception as exc:
        # The storing transaction rolled back as a whole; nothing half-written
        # remains. Record why on the source and let the run go on.
        reason = f"storing postings failed: {type(exc).__name__}"
        log.exception("crawl.source_store_failed", source_id=str(source.id), reason=reason)
        await ingest.record_crawl(source.id, [], error=reason)
        return CrawlOutcome(source.id, 0, 0, reason)
    return CrawlOutcome(source.id, upserted, expired, None)


async def embed_new_postings(ingest: CrawlIngest, model_name: str, batch: int = 200) -> int:
    """Embed every posting that has none yet, a batch at a time.
    Platform-paid computation."""
    embedded = 0
    while pending := await ingest.postings_needing_embeddings(model_name, limit=batch):
        vectors = embed([text for _id, text in pending], model_name=model_name)
        await ingest.store_embeddings(
            model_name,
            {posting_id: vector for (posting_id, _), vector in zip(pending, vectors, strict=True)},
        )
        embedded += len(pending)
        if len(pending) < batch:
            break
    return embedded


def _looks_like_json(text: str) -> bool:
    stripped = text.lstrip()
    return stripped.startswith(("{", "["))
