"""The market fetched only when a build needs it (ADR 0027), against a real
database: what a build marks due, what the crawler then sees, and that two
builds asking for the same new search at once share it."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import date, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import text

from advisor.market import (
    NormalizedPosting,
    SourceKind,
    create_crawl_ingest,
    create_market_service,
)
from kernel.clock import utcnow
from kernel.db import Database
from tests.integration.places import WINDOWS

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def title(database: Database, crawler_database: Database) -> AsyncIterator[str]:
    """A job title nobody else searches for, and the baseline boards put back
    as they were: every build also needs those, in a database other tests and
    the running stack share."""
    async with database.shared() as session:
        rows = await session.execute(
            text(
                "SELECT id, due_at, last_requested_at FROM market.crawl_source "
                "WHERE origin = 'baseline'"
            )
        )
        baseline = rows.all()
    tag = uuid.uuid4().hex[:10]
    yield f"Zyxwv {tag} Engineer"
    async with crawler_database.shared() as session:
        await session.execute(
            text(
                "DELETE FROM market.job_posting WHERE crawl_source_id IN "
                "(SELECT id FROM market.crawl_source WHERE endpoint LIKE :tag)"
            ),
            {"tag": f"%{tag}%"},
        )
        await session.execute(
            text("DELETE FROM market.crawl_source WHERE endpoint LIKE :tag"), {"tag": f"%{tag}%"}
        )
        for source_id, due_at, requested_at in baseline:
            await session.execute(
                text(
                    "UPDATE market.crawl_source SET due_at = :due, last_requested_at = :asked "
                    "WHERE id = :id"
                ),
                {"id": source_id, "due": due_at, "asked": requested_at},
            )


async def test_two_builds_asking_at_once_share_one_new_search(
    database: Database, title: str
) -> None:
    market = create_market_service(database, windows=WINDOWS)

    first, second = await asyncio.gather(
        market.request_sources(titles=[title], places=["Taiwan"], company_ids=[]),
        market.request_sources(titles=[title], places=["Taiwan"], company_ids=[]),
    )

    async with database.shared() as session:
        rows = await session.execute(
            text("SELECT id, market, company_id FROM market.crawl_source WHERE endpoint LIKE :t"),
            {"t": f"%{title.split()[1]}%"},
        )
        (search_id, place, company_id), *others = rows.all()
    assert others == [] and (place, company_id) == ("Taiwan", None)
    assert search_id in first.due and search_id in second.due


async def test_the_crawler_sees_what_is_due_and_a_fetch_within_the_window_is_reused(
    database: Database, crawler_database: Database, title: str
) -> None:
    market = create_market_service(database, windows=WINDOWS)
    ingest = create_crawl_ingest(crawler_database)
    asked = await market.request_sources(titles=[title], places=["Taiwan"], company_ids=[])
    baseline = set(await _baseline(database))
    search_id = next(i for i in asked.due if i not in baseline)

    assert search_id in {source.id for source in await ingest.due_sources()}

    found = NormalizedPosting(
        external_id="1",
        company_name=f"{title} Co",
        title=title,
        location="Remote, Taiwan",
        description="Build things.",
        url=f"https://himalayas.app/companies/x/jobs/{title.split()[1]}",
        source_kind=SourceKind.PUBLIC_API,
        posted_on=date(2026, 9, 1),
        salary=None,
    )
    assert await ingest.record_crawl(search_id, [found]) == (1, 0)
    await ingest.mark_fetched([search_id])

    assert search_id not in {source.id for source in await ingest.due_sources()}
    assert await market.pending_sources([search_id]) == ()
    results = await market.search_results(titles=[title], places=["Taiwan"])
    assert len(results[title]) == 1

    # A re-analysis with the same title an hour later: nothing to wait for.
    again = await market.request_sources(
        titles=[title], places=["Taiwan"], company_ids=[], at=utcnow() + timedelta(hours=1)
    )
    assert search_id in again.needed and search_id not in again.due


async def _baseline(database: Database) -> list[uuid.UUID]:
    async with database.shared() as session:
        rows = await session.execute(
            text("SELECT id FROM market.crawl_source WHERE origin = 'baseline'")
        )
        return list(rows.scalars())
