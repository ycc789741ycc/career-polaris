"""Market use cases against in-memory storage: what they decide, with no database."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from advisor.market import (
    BaselineSource,
    CrawlIngest,
    MarketService,
    NormalizedPosting,
    SalaryRange,
    SourceKind,
    Visibility,
)
from advisor.market.domain import (
    Company,
    CrawlSource,
    PostingsChanged,
    PostingStatus,
    SourceOrigin,
    SourceStatus,
    TargetLocationsChanged,
)
from kernel.errors import NotFoundError, ValidationError
from tests.unit.advisor.market.fakes import FakeMarketUnitOfWork

OWNER = uuid.UUID("00000000-0000-0000-0000-000000000001")
OTHER = uuid.UUID("00000000-0000-0000-0000-000000000002")


def _service(uow: FakeMarketUnitOfWork) -> MarketService:
    return MarketService(uow)


def _posting(title: str, *, company: str = "Acme", salary: SalaryRange | None = None):
    return NormalizedPosting(
        external_id=title,
        company_name=company,
        title=title,
        location="Berlin",
        description=f"{title} description",
        url=f"https://acme.test/{title}",
        source_kind=SourceKind.ATS_BOARD,
        posted_on=date(2026, 9, 1),
        salary=salary,
    )


# --- target locations ------------------------------------------------------


async def test_saving_the_same_target_locations_twice_announces_them_once() -> None:
    uow = FakeMarketUnitOfWork()
    market = _service(uow)

    await market.set_target_locations(OWNER, [" Remote EU ", "Berlin", "berlin"])
    chosen = await market.set_target_locations(OWNER, ["Berlin", "Remote EU"])

    assert chosen == ["Berlin", "Remote EU"]
    assert await market.target_locations(OWNER) == ["Berlin", "Remote EU"]
    assert uow.store.events == [
        TargetLocationsChanged(owner_id=OWNER, locations=("Berlin", "Remote EU"))
    ]


async def test_a_fourth_target_location_is_refused_and_nothing_changes() -> None:
    uow = FakeMarketUnitOfWork()
    market = _service(uow)
    await market.set_target_locations(OWNER, ["Berlin", "Lisbon", "Remote EU"])

    with pytest.raises(ValidationError):
        await market.set_target_locations(OWNER, ["Berlin", "Lisbon", "Remote EU", "Paris"])

    assert await market.target_locations(OWNER) == ["Berlin", "Lisbon", "Remote EU"]


async def test_removing_every_target_location_is_announced() -> None:
    uow = FakeMarketUnitOfWork()
    market = _service(uow)
    await market.set_target_locations(OWNER, ["Berlin"])

    assert await market.set_target_locations(OWNER, []) == []
    assert uow.store.events[-1] == TargetLocationsChanged(owner_id=OWNER, locations=())


async def test_the_scope_counts_the_open_shared_postings_in_the_target_locations() -> None:
    uow = FakeMarketUnitOfWork()
    ingest, market = CrawlIngest(uow), _service(uow)
    baseline = _source(uow, origin=SourceOrigin.BASELINE)
    await ingest.record_crawl(
        baseline.id,
        [
            replace(_posting("Backend"), location="Berlin, Germany"),
            replace(_posting("Data"), location="Lisbon, Portugal"),
        ],
    )
    await market.paste_job_description(
        OWNER, company_name="Acme", title="Staff", location="Berlin", description="JD"
    )
    await market.set_target_locations(OWNER, ["Berlin"])

    scope = await market.scope(OWNER)

    assert scope.target_locations == ["Berlin"]
    assert scope.open_posting_count == 1


async def test_the_fan_out_finds_the_users_whose_locations_take_in_a_market() -> None:
    uow = FakeMarketUnitOfWork()
    market = _service(uow)
    await market.set_target_locations(OWNER, ["Lisbon"])
    await market.set_target_locations(OTHER, ["Berlin"])

    assert await market.owners_affected_by(market="Berlin") == [OTHER]
    # A company's board changing reaches nobody through the fan-out on its own.
    assert await market.owners_affected_by(market=None) == []


# --- crawling --------------------------------------------------------------


def _source(
    uow: FakeMarketUnitOfWork, *, origin: SourceOrigin = SourceOrigin.DEMAND
) -> CrawlSource:
    seeded_at = datetime(2026, 1, 1, tzinfo=UTC)
    company = Company.named("Acme")
    company.created_at = seeded_at
    uow.store.companies[company.id] = company
    source = CrawlSource.board(
        kind="greenhouse", endpoint="https://boards.test/acme", company_id=company.id, origin=origin
    )
    source.created_at = seeded_at
    uow.store.sources[source.id] = source
    return source


async def test_a_crawl_upserts_what_it_saw_and_expires_what_it_did_not() -> None:
    uow = FakeMarketUnitOfWork()
    ingest = CrawlIngest(uow)
    source = _source(uow)

    await ingest.record_crawl(source.id, [_posting("Backend"), _posting("SRE")])
    upserted, expired = await ingest.record_crawl(source.id, [_posting("Backend")])

    assert (upserted, expired) == (1, 1)
    status = {p.title: p.status for p in uow.store.postings.values()}
    assert status == {"Backend": PostingStatus.OPEN, "SRE": PostingStatus.EXPIRED}
    assert uow.store.events[-1] == PostingsChanged(
        company_id=source.company_id, market=None, seen=1, expired=1
    )


async def test_a_repeat_sighting_keeps_published_pay_it_no_longer_shows() -> None:
    uow = FakeMarketUnitOfWork()
    ingest = CrawlIngest(uow)
    source = _source(uow)
    pay = SalaryRange(min_amount=90_000, max_amount=120_000, currency="EUR")

    await ingest.record_crawl(source.id, [_posting("Backend", salary=pay)])
    await ingest.record_crawl(source.id, [_posting("Backend")])

    (posting,) = uow.store.postings.values()
    assert posting.salary == pay
    assert posting.crawl_source_id == source.id


async def test_a_failed_crawl_is_recorded_and_changes_nothing_else() -> None:
    uow = FakeMarketUnitOfWork()
    ingest = CrawlIngest(uow)
    source = _source(uow)

    assert await ingest.record_crawl(source.id, [], error="timeout") == (0, 0)

    assert uow.store.sources[source.id].last_error == "timeout"
    assert uow.store.sources[source.id].last_fetched_at is not None
    assert uow.store.events == []


async def test_a_crawl_of_an_unknown_source_is_not_found() -> None:
    with pytest.raises(NotFoundError):
        await CrawlIngest(FakeMarketUnitOfWork()).record_crawl(uuid.uuid4(), [])


async def test_embedding_text_leads_with_the_title_twice() -> None:
    uow = FakeMarketUnitOfWork()
    ingest = CrawlIngest(uow)
    source = _source(uow)
    await ingest.record_crawl(source.id, [_posting("Backend")])

    [(posting_id, text)] = await ingest.postings_needing_embeddings("model")
    assert text == "Backend\nBackend\nBerlin\nBackend description"

    await ingest.store_embeddings("model", {posting_id: [0.1, 0.2]})
    assert await ingest.postings_needing_embeddings("model") == []


# --- scope -----------------------------------------------------------------


async def test_without_markets_the_scope_falls_back_to_baseline_postings() -> None:
    uow = FakeMarketUnitOfWork()
    ingest, market = CrawlIngest(uow), _service(uow)
    baseline = _source(uow, origin=SourceOrigin.BASELINE)
    await ingest.record_crawl(baseline.id, [_posting("Backend")])

    in_scope = await market.postings_in_scope(OWNER)
    assert [p.title for p in in_scope] == ["Backend"]

    # With a market chosen, only postings in it count, baseline or not.
    await market.set_target_locations(OWNER, ["Lisbon"])
    assert await market.postings_in_scope(OWNER) == []


async def test_a_market_takes_in_postings_whose_location_names_it() -> None:
    uow = FakeMarketUnitOfWork()
    ingest, market = CrawlIngest(uow), _service(uow)
    baseline = _source(uow, origin=SourceOrigin.BASELINE)
    await ingest.record_crawl(
        baseline.id,
        [
            replace(_posting("Backend"), location="Berlin, Germany"),
            replace(_posting("Platform"), location="München, Germany"),
            replace(_posting("Data"), location="Remote, United States"),
        ],
    )

    await market.set_target_locations(OWNER, ["berlin", "Munchen"])
    in_scope = await market.postings_in_scope(OWNER)
    assert sorted(p.title for p in in_scope) == ["Backend", "Platform"]


async def test_a_pasted_jd_is_private_and_links_to_its_crawled_twin() -> None:
    uow = FakeMarketUnitOfWork()
    ingest, market = CrawlIngest(uow), _service(uow)
    await ingest.record_crawl(_source(uow).id, [_posting("Backend")])

    pasted = await market.paste_job_description(
        OWNER, company_name="Acme", title="Backend", location="Berlin", description="JD"
    )

    assert pasted.visibility is Visibility.PRIVATE
    (stored,) = uow.store.private_postings.values()
    (crawled,) = uow.store.postings.values()
    assert stored.shared_posting_id == crawled.id
    assert await market.private_postings(OTHER) == []


# --- baseline and demand sources -------------------------------------------


async def test_seeding_the_baseline_retires_what_is_no_longer_listed() -> None:
    uow = FakeMarketUnitOfWork()
    market = _service(uow)
    kept = BaselineSource(kind="lever", company_name="Kept", endpoint="https://lever.test/kept")
    dropped = BaselineSource(kind="lever", company_name="Gone", endpoint="https://lever.test/gone")

    assert await market.seed_baseline((kept, dropped)) == (2, 0)
    assert await market.seed_baseline((kept,)) == (1, 1)
    assert await market.seed_baseline((kept,)) == (1, 0)

    status = {s.endpoint: s.status for s in uow.store.sources.values()}
    assert status == {kept.endpoint: SourceStatus.ACTIVE, dropped.endpoint: SourceStatus.RETIRED}


def _company(uow: FakeMarketUnitOfWork, name: str = "Acme") -> Company:
    company = Company.named(name)
    uow.store.companies[company.id] = company
    return company


async def test_a_demand_board_becomes_baseline_when_listed() -> None:
    uow = FakeMarketUnitOfWork()
    market = _service(uow)
    company = _company(uow)
    await market.register_board(company.id, kind="lever", endpoint="https://lever.test/a")
    await market.register_board(company.id, kind="lever", endpoint="https://lever.test/a")

    await market.seed_baseline(
        (BaselineSource(kind="lever", company_name="Acme", endpoint="https://lever.test/a"),)
    )

    (source,) = uow.store.sources.values()
    assert source.origin is SourceOrigin.BASELINE
    assert source.company_id == company.id


async def test_a_company_with_a_board_needs_no_discovery() -> None:
    uow = FakeMarketUnitOfWork()
    market = _service(uow)
    company = _company(uow)

    assert await market.company_needing_source(company.id, "Acme") == "Acme"
    await market.register_board(company.id, kind="lever", endpoint="https://lever.test/acme")

    assert await market.company_needing_source(company.id, "Acme") is None
    (source,) = uow.store.sources.values()
    assert source.origin is SourceOrigin.DEMAND
