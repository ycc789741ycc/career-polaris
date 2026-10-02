"""The crawler's write path, against a real database.

Dedup, expiry and the privacy of pasted JDs are the things worth proving here;
they are the rules that quietly stop being true if someone refactors a query.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy import text

from advisor.market import (
    NormalizedPosting,
    SourceKind,
    Visibility,
    create_crawl_ingest,
    create_market_service,
)
from advisor.market.infra.models import CrawlSource
from kernel.db import Database
from tests.integration.places import WINDOWS, store_target_locations

pytestmark = pytest.mark.integration


# Postings dedup globally by company + title + location, so each test needs its
# own company or it collides with rows another test left behind.
COMPANY = f"Testco {uuid.uuid4().hex[:8]}"


def posting(title: str, *, company: str = COMPANY, location: str | None = "Berlin"):
    return NormalizedPosting(
        external_id=title.lower().replace(" ", "-"),
        company_name=company,
        title=title,
        location=location,
        description=f"You will work on {title}.",
        url=f"https://boards.test/{title}",
        source_kind=SourceKind.ATS_BOARD,
        posted_on=date(2026, 9, 1),
        salary=None,
    )


@pytest_asyncio.fixture
async def source(crawler_database: Database):
    """A throwaway crawl source, created and cleaned up with the crawler role.

    app_rw cannot delete postings — only the crawler writes the shared zone —
    so the whole fixture lives on that connection.
    """
    async with crawler_database.shared() as session:
        row = CrawlSource(kind="greenhouse", endpoint=f"https://boards.test/{uuid.uuid4()}")
        session.add(row)
        await session.flush()
        source_id = row.id
    yield source_id
    async with crawler_database.shared() as session:
        await session.execute(
            text("DELETE FROM market.job_posting WHERE crawl_source_id = :id"),
            {"id": source_id},
        )
        await session.execute(
            text("DELETE FROM market.crawl_source WHERE id = :id"), {"id": source_id}
        )


async def test_a_crawl_stores_normalised_postings(crawler_database: Database, source) -> None:
    ingest = create_crawl_ingest(crawler_database)
    upserted, expired = await ingest.record_crawl(
        source, [posting("Senior Backend Engineer"), posting("Platform Engineer")]
    )
    assert (upserted, expired) == (2, 0)

    async with crawler_database.shared() as session:
        count = await session.execute(
            text("SELECT count(*) FROM market.job_posting WHERE crawl_source_id = :id"),
            {"id": source},
        )
        assert count.scalar_one() == 2


async def test_the_same_job_seen_twice_does_not_duplicate(
    database: Database, crawler_database: Database, source
) -> None:
    """The dedup key is what keeps one opening from becoming two."""
    ingest = create_crawl_ingest(crawler_database)
    await ingest.record_crawl(source, [posting("Senior Backend Engineer (m/f/d)")])
    await ingest.record_crawl(source, [posting("Senior Backend Engineer")])

    async with database.shared() as session:
        count = await session.execute(
            text("SELECT count(*) FROM market.job_posting WHERE crawl_source_id = :id"),
            {"id": source},
        )
        assert count.scalar_one() == 1


async def test_a_posting_missing_from_a_crawl_is_expired_not_deleted(
    database: Database, crawler_database: Database, source
) -> None:
    """Expired postings still count toward salary history."""
    ingest = create_crawl_ingest(crawler_database)
    await ingest.record_crawl(source, [posting("Senior Backend Engineer"), posting("Gone Role")])
    await ingest.record_crawl(source, [posting("Senior Backend Engineer")])

    async with database.shared() as session:
        rows = await session.execute(
            text(
                "SELECT title, status FROM market.job_posting "
                "WHERE crawl_source_id = :id ORDER BY title"
            ),
            {"id": source},
        )
        assert {title: status for title, status in rows.all()} == {
            "Gone Role": "expired",
            "Senior Backend Engineer": "open",
        }


async def test_a_pasted_jd_never_reaches_the_shared_tables(
    database: Database, account: uuid.UUID
) -> None:
    market = create_market_service(database, windows=WINDOWS)
    pasted = await market.paste_job_description(
        account,
        company_name="Uncrawlable Ltd",
        title="Staff Engineer",
        location="Remote EU",
        description="A JD the user pasted themselves.",
    )
    assert pasted.visibility is Visibility.PRIVATE

    async with database.shared() as session:
        leaked = await session.execute(
            text("SELECT count(*) FROM market.job_posting WHERE title = 'Staff Engineer'")
        )
        assert leaked.scalar_one() == 0


async def test_another_users_pasted_jd_is_not_in_my_scope(
    database: Database, account: uuid.UUID, other_account: uuid.UUID
) -> None:
    market = create_market_service(database, windows=WINDOWS)
    await market.paste_job_description(
        other_account,
        company_name="Theirs",
        title="Their Private Role",
        location=None,
        description="Only for them.",
    )
    mine = await market.postings_in_scope(account)
    assert all(p.title != "Their Private Role" for p in mine)


# -- the baseline boards -----------------------------------------------------


async def _company(crawler_database: Database, name: str):
    from advisor.market.domain import Company
    from advisor.market.infra.unit_of_work import SqlAlchemyMarketUnitOfWork

    async with SqlAlchemyMarketUnitOfWork(crawler_database).shared() as market:
        return await market.companies.create(Company.named(name))


async def test_seeding_the_baseline_is_idempotent_and_retires_what_was_dropped(
    database: Database, crawler_database: Database
) -> None:
    from advisor.market import BASELINE_SOURCES, BaselineSource

    extra = BaselineSource(
        "greenhouse",
        f"Baseline Test {uuid.uuid4().hex[:8]}",
        f"https://boards-api.greenhouse.io/v1/boards/{uuid.uuid4().hex}/jobs?content=true",
    )
    market = create_market_service(database, windows=WINDOWS)

    async def rows_for(endpoint: str) -> list[tuple[str, str]]:
        async with database.shared() as session:
            found = await session.execute(
                text("SELECT origin, status FROM market.crawl_source WHERE endpoint = :e"),
                {"e": endpoint},
            )
            return [tuple(row) for row in found.all()]

    try:
        await market.seed_baseline((*BASELINE_SOURCES, extra))
        await market.seed_baseline((*BASELINE_SOURCES, extra))
        assert await rows_for(extra.endpoint) == [("baseline", "active")]

        # Dropped from the list: retired, not deleted.
        _active, retired = await market.seed_baseline(BASELINE_SOURCES)
        assert retired == 1
        assert await rows_for(extra.endpoint) == [("baseline", "retired")]
        for source in BASELINE_SOURCES:
            assert await rows_for(source.endpoint) == [("baseline", "active")]
    finally:
        async with crawler_database.shared() as session:
            await session.execute(
                text("DELETE FROM market.crawl_source WHERE endpoint = :e"),
                {"e": extra.endpoint},
            )


async def test_a_user_with_no_market_sees_baseline_postings_and_one_with_a_market_does_not(
    database: Database,
    crawler_database: Database,
    account: uuid.UUID,
    other_account: uuid.UUID,
) -> None:
    company = f"Baseline Co {uuid.uuid4().hex[:8]}"
    async with crawler_database.shared() as session:
        row = CrawlSource(
            kind="greenhouse",
            endpoint=f"https://boards.test/{uuid.uuid4()}",
            origin="baseline",
        )
        session.add(row)
        await session.flush()
        source_id = row.id
    try:
        await create_crawl_ingest(crawler_database).record_crawl(
            source_id, [posting("Baseline Engineer", company=company, location="Lisbon")]
        )
        market = create_market_service(database, windows=WINDOWS)
        await store_target_locations(database, other_account, [f"Elsewhere {uuid.uuid4().hex[:8]}"])

        mine = await market.postings_in_scope(account)
        theirs = await market.postings_in_scope(other_account)

        assert any(p.company_name == company for p in mine)
        assert all(p.company_name != company for p in theirs)
    finally:
        async with crawler_database.shared() as session:
            await session.execute(
                text("DELETE FROM market.job_posting WHERE crawl_source_id = :id"),
                {"id": source_id},
            )
            await session.execute(
                text("DELETE FROM market.crawl_source WHERE id = :id"), {"id": source_id}
            )


async def test_a_posting_listing_every_office_still_stores(
    crawler_database: Database, source
) -> None:
    """A board once sent a location naming dozens of offices; storing it failed
    and took the whole crawl down with it."""
    ingest = create_crawl_ingest(crawler_database)
    every_office = "; ".join(f"Remote, US State {n}" for n in range(60))

    upserted, _ = await ingest.record_crawl(
        source, [posting("Staff Application Security Engineer", location=every_office)]
    )

    assert upserted == 1
    async with crawler_database.shared() as session:
        stored = await session.execute(
            text(
                "SELECT location, canonical_key FROM market.job_posting WHERE crawl_source_id = :id"
            ),
            {"id": source},
        )
        location, key = stored.one()
    assert len(location) == 255 and location.endswith("…")
    assert len(key) <= 768
