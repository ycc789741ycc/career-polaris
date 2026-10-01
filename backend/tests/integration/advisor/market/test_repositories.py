"""The SQLAlchemy side of the market's repositories, against a real database.

What is worth proving here, beyond the use-case tests:
- every entity survives the trip through its mapper;
- the six methods keep their contract: newest first, paging, counting, and
  not-found from ``update`` and ``delete``;
- an owner scope sees one owner's rows and nobody else's;
- each domain event lands in the outbox under the name and payload the
  dispatcher reads.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import text

from advisor.market.domain import (
    Company,
    CompanyFilter,
    CrawlSource,
    CrawlSourceFilter,
    JobPosting,
    JobPostingFilter,
    MarketPreference,
    MarketPreferenceFilter,
    NormalizedPosting,
    PostingEmbedding,
    PostingEmbeddingFilter,
    PostingScope,
    PostingStatus,
    PrivateJobPosting,
    PrivateJobPostingFilter,
    SalaryRange,
    SearchResultFilter,
    SourceKind,
    SourceOrigin,
    TargetLocationsChanged,
)
from advisor.market.infra.unit_of_work import SqlAlchemyMarketUnitOfWork
from kernel.db import Database
from kernel.errors import NotFoundError, ValidationError
from tests.integration.places import WINDOWS

pytestmark = pytest.mark.integration


async def test_the_six_methods_keep_their_contract(database: Database, account: uuid.UUID) -> None:
    uow = SqlAlchemyMarketUnitOfWork(database)
    tag = uuid.uuid4().hex[:8]

    # One transaction each: created_at is the transaction's start time.
    created = []
    for place in ("First", "Second", "Third"):
        async with uow.for_owner(account) as mine:
            created.append(
                await mine.markets.create(
                    MarketPreference.chosen(owner_id=account, market=f"{place} {tag}")
                )
            )
    assert all(m.created_at is not None and m.updated_at is not None for m in created)

    async with uow.for_owner(account) as mine:
        everything = MarketPreferenceFilter()
        newest_first = await mine.markets.get_list(everything)
        expected = [f"{place} {tag}" for place in ("Third", "Second", "First")]
        assert [m.market for m in newest_first] == expected
        assert newest_first[-1] == created[0]
        assert [m.market for m in await mine.markets.get_list(everything, 2, 2)] == [f"First {tag}"]
        assert await mine.markets.get_count(everything) == 3
        assert await mine.markets.get_count(MarketPreferenceFilter(market=f"Second {tag}")) == 1
        with pytest.raises(ValidationError):
            await mine.markets.get_list(everything, page=3)

        first = created[0]
        first.market = f"Renamed {tag}"
        updated = await mine.markets.update(first)
        assert updated.market == f"Renamed {tag}"
        assert await mine.markets.get(first.id) == updated

        await mine.markets.delete(first.id)
        assert await mine.markets.get(first.id) is None
        with pytest.raises(NotFoundError):
            await mine.markets.delete(first.id)
        with pytest.raises(NotFoundError):
            await mine.markets.update(first)


async def test_an_owner_scope_sees_nobody_elses_rows(
    database: Database, account: uuid.UUID, other_account: uuid.UUID
) -> None:
    uow = SqlAlchemyMarketUnitOfWork(database)
    place = f"Berlin {uuid.uuid4().hex[:8]}"
    async with uow.for_owner(account) as mine:
        preference = await mine.markets.create(
            MarketPreference.chosen(owner_id=account, market=place)
        )

    async with uow.for_owner(other_account) as theirs:
        assert await theirs.markets.get(preference.id) is None
        assert await theirs.markets.get_count(MarketPreferenceFilter()) == 0
        with pytest.raises(NotFoundError):
            await theirs.markets.delete(preference.id)

    # Nothing reads target locations across users any more (ADR 0027): the
    # setting the fan-out policy was gated on opens nothing.
    async with database.shared() as session:
        await session.execute(text("SELECT set_config('app.fanout', 'on', true)"))
        rows = await session.execute(
            text("SELECT count(*) FROM market_user.market_preference WHERE market = :place"),
            {"place": place},
        )
        assert rows.scalar_one() == 0


async def test_pasted_jds_round_trip(database: Database, account: uuid.UUID) -> None:
    uow = SqlAlchemyMarketUnitOfWork(database)
    vector = [0.0] * 383 + [1.0]

    async with uow.for_owner(account) as mine:
        pasted = await mine.private_postings.create(
            PrivateJobPosting.pasted(
                owner_id=account,
                company_name=" Repo Co ",
                title="Backend",
                location=None,
                description="JD",
                url=None,
                shared_posting_id=None,
            )
        )

    async with uow.for_owner(account) as mine:
        assert await mine.private_postings.get(pasted.id) == pasted
        assert await mine.private_postings.get_count(PrivateJobPostingFilter(has_vector=True)) == 0
        pasted.vector = vector
        await mine.private_postings.update(pasted)
        [embedded] = await mine.private_postings.get_list(PrivateJobPostingFilter(has_vector=True))
        assert embedded.vector == vector


async def test_shared_postings_round_trip_through_the_crawler_role(
    crawler_database: Database,
) -> None:
    uow = SqlAlchemyMarketUnitOfWork(crawler_database)
    seen_at = datetime(2026, 9, 27, 12, tzinfo=UTC)
    async with uow.shared() as market:
        company = await market.companies.create(Company.named(f"Repo Co {uuid.uuid4().hex[:8]}"))
        source = await market.sources.create(
            CrawlSource.board(
                kind="greenhouse",
                endpoint=f"https://boards.test/{uuid.uuid4()}",
                company_id=company.id,
                origin=SourceOrigin.DEMAND,
            )
        )
    seen = NormalizedPosting(
        external_id="1",
        company_name=company.name,
        title="Backend",
        location="Berlin",
        description="Build things.",
        url="https://boards.test/1",
        source_kind=SourceKind.ATS_BOARD,
        posted_on=date(2026, 9, 1),
        salary=SalaryRange(min_amount=90_000, max_amount=120_000, currency="EUR"),
    )
    try:
        async with uow.shared() as market:
            posting = await market.postings.create(
                JobPosting.first_seen(seen, company_id=company.id, source_id=source.id, at=seen_at)
            )

        async with uow.shared() as market:
            assert await market.companies.get_list(
                CompanyFilter(normalized_name=company.normalized_name)
            ) == [company]
            assert await market.sources.get_list(CrawlSourceFilter(endpoint=source.endpoint)) == [
                source
            ]
            [loaded] = await market.postings.get_list(
                JobPostingFilter(canonical_key=seen.canonical_key)
            )
            assert loaded == posting
            assert (
                await market.postings.get_count(
                    JobPostingFilter(ids=(posting.id,), has_salary=True)
                )
                == 1
            )
            assert posting in await market.postings.get_open_in_scope(
                PostingScope(markets=("Berlin",))
            )
            # A country takes in its cities, and a region its countries (ADR 0026).
            for place in ("Germany", "Europe"):
                assert posting in await market.postings.get_open_in_scope(
                    PostingScope(markets=(place,))
                )
            assert posting not in await market.postings.get_open_in_scope(
                PostingScope(markets=("Asia-Pacific",))
            )

            assert (
                await market.postings.get_count(
                    JobPostingFilter(ids=(posting.id,), missing_embedding_for="model")
                )
                == 1
            )
            await market.embeddings.create(
                PostingEmbedding(posting_id=posting.id, model_name="model", vector=[0.5] * 384)
            )
            assert (
                await market.postings.get_count(
                    JobPostingFilter(ids=(posting.id,), missing_embedding_for="model")
                )
                == 0
            )
            [embedding] = await market.embeddings.get_list(
                PostingEmbeddingFilter(posting_ids=(posting.id,), model_name="model")
            )
            assert embedding.vector == [0.5] * 384

        async with uow.shared() as market:
            assert await market.postings.expire_unseen(source.id, set()) == 1
        async with uow.shared() as market:
            expired = await market.postings.get(posting.id)
            assert expired is not None and expired.status is PostingStatus.EXPIRED
    finally:
        async with crawler_database.shared() as session:
            for table, column in (
                ("market.job_posting", "crawl_source_id"),
                ("market.crawl_source", "id"),
            ):
                await session.execute(
                    text(f"DELETE FROM {table} WHERE {column} = :id"), {"id": source.id}
                )


async def test_a_market_scope_matches_locations_by_their_words(
    crawler_database: Database,
) -> None:
    uow = SqlAlchemyMarketUnitOfWork(crawler_database)
    # A made-up place per run, so real postings in the database never match.
    place = f"Zyrich{uuid.uuid4().hex[:8]}"
    seen_at = datetime(2026, 9, 27, 12, tzinfo=UTC)
    async with uow.shared() as market:
        company = await market.companies.create(Company.named(f"Repo Co {uuid.uuid4().hex[:8]}"))
        source = await market.sources.create(
            CrawlSource.board(
                kind="greenhouse",
                endpoint=f"https://boards.test/{uuid.uuid4()}",
                company_id=company.id,
                origin=SourceOrigin.DEMAND,
            )
        )

    def seen(title: str, location: str) -> NormalizedPosting:
        return NormalizedPosting(
            external_id=title,
            company_name=company.name,
            title=title,
            location=location,
            description="Build things.",
            url=f"https://boards.test/{title}",
            source_kind=SourceKind.ATS_BOARD,
            posted_on=date(2026, 9, 1),
            salary=None,
        )

    try:
        postings = {}
        async with uow.shared() as market:
            for title, location in (
                ("in-city", f"{place}, Germany"),
                ("accented", f"{place.replace('y', 'ü', 1)} Nord, Germany"),
                ("prefix-only", f"{place}er Land, Germany"),
            ):
                postings[title] = await market.postings.create(
                    JobPosting.first_seen(
                        seen(title, location),
                        company_id=company.id,
                        source_id=source.id,
                        at=seen_at,
                    )
                )
            await market.search_results.replace(
                source.id, [p.id for p in postings.values()], at=seen_at
            )

        async with uow.shared() as market:
            in_scope = await market.postings.get_open_in_scope(
                PostingScope(markets=(place.lower(),))
            )
            typed_with_accent = await market.postings.get_open_in_scope(
                PostingScope(markets=(f"{place.replace('y', 'ü', 1)} Nord",))
            )
            typed_without = await market.postings.get_open_in_scope(
                PostingScope(markets=(f"{place.replace('y', 'u', 1)} nord",))
            )
            wordless = await market.postings.get_open_in_scope(PostingScope(markets=("---",)))
        ids = {p.id for p in in_scope}
        assert postings["in-city"].id in ids
        assert postings["prefix-only"].id not in ids
        assert postings["accented"].id not in ids
        # The database folds "ü" to "u" as normalize does, so either spelling
        # of the market reaches the accented location.
        assert [p.id for p in typed_with_accent] == [postings["accented"].id]
        assert [p.id for p in typed_without] == [postings["accented"].id]
        assert wordless == []
    finally:
        async with crawler_database.shared() as session:
            for table, column in (
                ("market.job_posting", "crawl_source_id"),
                ("market.crawl_source", "id"),
            ):
                await session.execute(
                    text(f"DELETE FROM {table} WHERE {column} = :id"), {"id": source.id}
                )


async def test_owner_events_reach_the_outbox_as_the_dispatcher_reads_them(
    database: Database, account: uuid.UUID
) -> None:
    uow = SqlAlchemyMarketUnitOfWork(database)

    async with uow.for_owner(account) as mine:
        mine.record(TargetLocationsChanged(owner_id=account, locations=("Berlin",)))

    async with database.shared() as session:
        rows = await session.execute(
            text("SELECT name, payload FROM outbox.event WHERE owner_id = :owner"),
            {"owner": account},
        )
        assert [tuple(row) for row in rows.all()] == [
            ("TargetLocationsChanged", {"locations": ["Berlin"]})
        ]


async def test_nothing_recorded_in_a_failed_scope_reaches_the_outbox(
    database: Database, account: uuid.UUID
) -> None:
    uow = SqlAlchemyMarketUnitOfWork(database)
    with pytest.raises(RuntimeError):
        async with uow.for_owner(account) as mine:
            mine.record(TargetLocationsChanged(owner_id=account, locations=("Nowhere",)))
            raise RuntimeError("the use case failed")

    async with database.shared() as session:
        rows = await session.execute(
            text("SELECT count(*) FROM outbox.event WHERE owner_id = :owner"), {"owner": account}
        )
        assert rows.scalar_one() == 0


# --- searches of a public job API (ADR 0025) --------------------------------


async def test_a_search_source_round_trips_and_is_found_while_due_or_idle(
    crawler_database: Database,
) -> None:
    uow = SqlAlchemyMarketUnitOfWork(crawler_database)
    asked = datetime(2026, 9, 1, 12, tzinfo=UTC)
    endpoint = f"https://himalayas.app/jobs/api/search?q={uuid.uuid4().hex}&country=TW"
    async with uow.shared() as market:
        source = await market.sources.create(
            CrawlSource.search(kind="himalayas", endpoint=endpoint, market="Taiwan", at=asked)
        )
    try:
        async with uow.shared() as market:
            [loaded] = await market.sources.get_list(CrawlSourceFilter(endpoint=endpoint))
            assert loaded == source
            assert (loaded.last_requested_at, loaded.company_id) == (asked, None)
            assert (loaded.origin, loaded.market) == (SourceOrigin.DEMAND, "Taiwan")

            due = CrawlSourceFilter(endpoint=endpoint, is_due=True, is_search=True)
            waiting = CrawlSourceFilter(endpoint=endpoint, is_due=False)
            assert await market.sources.get_count(due) == 0
            assert await market.sources.get_count(waiting) == 1
            assert (
                await market.sources.get_count(
                    CrawlSourceFilter(endpoint=endpoint, is_search=False)
                )
                == 0
            )

            idle = CrawlSourceFilter(
                endpoint=endpoint, requested_before=datetime(2026, 9, 2, tzinfo=UTC)
            )
            wanted = CrawlSourceFilter(endpoint=endpoint, requested_before=asked)
            assert await market.sources.get_count(idle) == 1
            assert await market.sources.get_count(wanted) == 0

            loaded.due_at = datetime(2026, 9, 3, tzinfo=UTC)
            await market.sources.update(loaded)
            assert await market.sources.get_count(due) == 1
            assert await market.sources.get_count(waiting) == 0
            # Asked for again at once: one row, whoever asked.
            assert not await market.sources.create_if_absent(
                CrawlSource.search(kind="himalayas", endpoint=endpoint, market="Taiwan", at=asked)
            )
            assert await market.sources.get_count(CrawlSourceFilter(endpoint=endpoint)) == 1
    finally:
        async with crawler_database.shared() as session:
            await session.execute(
                text("DELETE FROM market.crawl_source WHERE id = :id"), {"id": source.id}
            )


async def test_a_board_is_never_idle_for_lack_of_demand(crawler_database: Database) -> None:
    uow = SqlAlchemyMarketUnitOfWork(crawler_database)
    endpoint = f"https://boards.test/{uuid.uuid4()}"
    async with uow.shared() as market:
        company = await market.companies.create(Company.named(f"Repo Co {uuid.uuid4().hex[:8]}"))
        board = await market.sources.create(
            CrawlSource.board(
                kind="greenhouse",
                endpoint=endpoint,
                company_id=company.id,
                origin=SourceOrigin.DEMAND,
            )
        )
    try:
        async with uow.shared() as market:
            far_future = CrawlSourceFilter(
                endpoint=endpoint, requested_before=datetime(2999, 1, 1, tzinfo=UTC)
            )
            assert await market.sources.get_count(far_future) == 0
    finally:
        async with crawler_database.shared() as session:
            await session.execute(
                text("DELETE FROM market.crawl_source WHERE id = :id"), {"id": board.id}
            )


async def test_remote_work_open_to_anyone_is_in_scope_wherever_a_search_covers(
    crawler_database: Database,
) -> None:
    uow = SqlAlchemyMarketUnitOfWork(crawler_database)
    # Long ago, so the thinning below can reach nothing but these postings in a
    # database other tests and the running stack share.
    seen_at = datetime(2001, 1, 1, tzinfo=UTC)
    async with uow.shared() as market:
        company = await market.companies.create(Company.named(f"Repo Co {uuid.uuid4().hex[:8]}"))
        source = await market.sources.create(
            CrawlSource.search(
                kind="himalayas",
                endpoint=f"https://himalayas.app/jobs/api/search?q={uuid.uuid4().hex}&country=TW",
                market="Taiwan",
                at=seen_at,
            )
        )

    def seen(title: str, location: str) -> NormalizedPosting:
        return NormalizedPosting(
            external_id=title,
            company_name=company.name,
            title=title,
            location=location,
            description="Build things.",
            url=f"https://himalayas.app/companies/repo/jobs/{title}",
            source_kind=SourceKind.PUBLIC_API,
            posted_on=date(2026, 9, 1),
            salary=None,
        )

    try:
        postings = {}
        async with uow.shared() as market:
            for title, location in (
                ("anyone", "Remote, Worldwide"),
                ("taiwan", "Remote, Taiwan, Japan"),
                ("elsewhere", "Remote, Argentina"),
            ):
                postings[title] = await market.postings.create(
                    JobPosting.first_seen(
                        seen(title, location),
                        company_id=company.id,
                        source_id=source.id,
                        at=seen_at,
                    )
                )
            await market.search_results.replace(
                source.id, [p.id for p in postings.values()], at=seen_at
            )

        async def in_scope(*markets: str) -> set[str]:
            async with uow.shared() as market:
                found = await market.postings.get_open_in_scope(PostingScope(markets=markets))
            mine = {p.id: title for title, p in postings.items()}
            return {mine[p.id] for p in found if p.id in mine}

        assert await in_scope("Taiwan") == {"anyone", "taiwan"}
        assert await in_scope("Remote Taiwan") == {"anyone", "taiwan"}
        assert await in_scope("Remote") == {"anyone", "taiwan", "elsewhere"}
        assert await in_scope("Singapore") == {"anyone"}
        # A city is no place a search covers, so worldwide work is not in it.
        assert await in_scope("Taipei") == set()

        # Off the search's current list, a posting leaves every scope, still
        # open (ADR 0027).
        async with uow.shared() as market:
            await market.search_results.replace(source.id, [postings["anyone"].id], at=seen_at)
            listed = await market.search_results.get_list(
                SearchResultFilter(crawl_source_ids=(source.id,))
            )
        assert [r.job_posting_id for r in listed] == [postings["anyone"].id]
        assert await in_scope("Remote") == {"anyone"}

        # Nothing holds the others now: past the age, they are thinned.
        async with uow.shared() as market:
            thinned = await market.postings.thin_unheld(
                unseen_since=datetime(2001, 1, 2, tzinfo=UTC),
                at=datetime(2026, 10, 2, tzinfo=UTC),
            )
            kept = await market.postings.get(postings["taiwan"].id)
            held = await market.postings.get(postings["anyone"].id)
        assert thinned == 2
        assert kept is not None and kept.description == "" and kept.thinned_at is not None
        assert held is not None and held.description == "Build things."
    finally:
        async with crawler_database.shared() as session:
            for table, column in (
                ("market.job_posting", "crawl_source_id"),
                ("market.crawl_source", "id"),
            ):
                await session.execute(
                    text(f"DELETE FROM {table} WHERE {column} = :id"), {"id": source.id}
                )


async def test_only_places_on_the_list_are_saved(database: Database, account: uuid.UUID) -> None:
    from advisor.market import create_market_service

    market = create_market_service(database, windows=WINDOWS)

    assert await market.set_target_locations(account, ["united kingdom", "Remote"]) == [
        "Remote",
        "United Kingdom",
    ]
    with pytest.raises(ValidationError):
        await market.set_target_locations(account, ["Taipei"])
    assert await market.target_locations(account) == ["Remote", "United Kingdom"]
