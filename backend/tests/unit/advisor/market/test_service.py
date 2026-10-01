"""Market use cases against in-memory storage: what they decide, with no database."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from advisor.market import (
    BaselineSource,
    CrawlIngest,
    MarketService,
    NormalizedPosting,
    SalaryRange,
    SourceKind,
    TargetLocationOptionView,
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

    await market.set_target_locations(OWNER, [" remote ", "Germany", "germany"])
    chosen = await market.set_target_locations(OWNER, ["Germany", "Remote"])

    assert chosen == ["Germany", "Remote"]
    assert await market.target_locations(OWNER) == ["Germany", "Remote"]
    assert uow.store.events == [
        TargetLocationsChanged(owner_id=OWNER, locations=("Germany", "Remote"))
    ]


async def test_a_place_not_on_the_list_is_refused_and_nothing_changes() -> None:
    uow = FakeMarketUnitOfWork()
    market = _service(uow)
    await market.set_target_locations(OWNER, ["Taiwan"])

    with pytest.raises(ValidationError):
        await market.set_target_locations(OWNER, ["Taiwan", "Taipei"])

    assert await market.target_locations(OWNER) == ["Taiwan"]


def test_the_options_are_the_list_with_their_kinds() -> None:
    options = _service(FakeMarketUnitOfWork()).target_location_options()

    assert options[0] == TargetLocationOptionView(name="Remote", kind="remote")
    assert TargetLocationOptionView(name="Europe", kind="region") in options
    assert TargetLocationOptionView(name="Taiwan", kind="country") in options


async def test_a_fourth_target_location_is_refused_and_nothing_changes() -> None:
    uow = FakeMarketUnitOfWork()
    market = _service(uow)
    await market.set_target_locations(OWNER, ["Germany", "Portugal", "Remote"])

    with pytest.raises(ValidationError):
        await market.set_target_locations(OWNER, ["Germany", "Portugal", "Remote", "France"])

    assert await market.target_locations(OWNER) == ["Germany", "Portugal", "Remote"]


async def test_removing_every_target_location_is_announced() -> None:
    uow = FakeMarketUnitOfWork()
    market = _service(uow)
    await market.set_target_locations(OWNER, ["Germany"])

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
    await market.set_target_locations(OWNER, ["Germany"])

    scope = await market.scope(OWNER)

    assert scope.target_locations == ["Germany"]
    assert scope.open_posting_count == 1


async def test_the_fan_out_finds_the_users_whose_locations_take_in_a_market() -> None:
    uow = FakeMarketUnitOfWork()
    market = _service(uow)
    await market.set_target_locations(OWNER, ["Portugal"])
    await market.set_target_locations(OTHER, ["Germany"])

    assert await market.owners_affected_by(market="Germany") == [OTHER]
    # A company's board changing reaches nobody through the fan-out on its own.
    assert await market.owners_affected_by(market=None) == []


async def test_the_fan_out_reaches_the_users_of_a_country_and_of_its_regions() -> None:
    """A change to a country's postings concerns whoever chose a region it is
    in, too (ADR 0026)."""
    uow = FakeMarketUnitOfWork()
    market = _service(uow)
    third = uuid.UUID("00000000-0000-0000-0000-000000000003")
    await market.set_target_locations(OWNER, ["Taiwan", "Remote"])
    await market.set_target_locations(OTHER, ["Asia-Pacific"])
    await market.set_target_locations(third, ["United Kingdom"])

    assert await market.owners_affected_by(market="Taiwan") == [OWNER, OTHER]
    assert await market.owners_affected_by(market="Singapore") == [OTHER]
    assert await market.owners_affected_by(market="United Kingdom") == [third]
    assert await market.owners_affected_by(market="Remote") == [OWNER]


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
    await market.set_target_locations(OWNER, ["Portugal"])
    assert await market.postings_in_scope(OWNER) == []


async def test_a_place_takes_in_postings_naming_it_or_one_of_its_cities() -> None:
    uow = FakeMarketUnitOfWork()
    ingest, market = CrawlIngest(uow), _service(uow)
    baseline = _source(uow, origin=SourceOrigin.BASELINE)
    await ingest.record_crawl(
        baseline.id,
        [
            replace(_posting("Backend"), location="Berlin, Germany"),
            replace(_posting("Platform"), location="München"),
            replace(_posting("Data"), location="Remote, United States"),
            replace(_posting("Infra"), location="Taipei"),
        ],
    )

    await market.set_target_locations(OWNER, ["Germany"])
    in_scope = await market.postings_in_scope(OWNER)
    assert sorted(p.title for p in in_scope) == ["Backend", "Platform"]

    await market.set_target_locations(OWNER, ["Europe", "Asia-Pacific"])
    in_scope = await market.postings_in_scope(OWNER)
    assert sorted(p.title for p in in_scope) == ["Backend", "Infra", "Platform"]


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


# --- searches of a public job API (ADR 0025) --------------------------------

SEARCH = "https://himalayas.app/jobs/api/search?q=data%20engineer&country=TW"
NOW = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)


def _remote(title: str, location: str = "Remote, Taiwan") -> NormalizedPosting:
    return replace(_posting(title), location=location, source_kind=SourceKind.PUBLIC_API)


async def test_a_search_asked_for_is_an_ownerless_demand_source_filed_under_its_place() -> None:
    uow = FakeMarketUnitOfWork()

    created = await _service(uow).request_searches(
        kind="himalayas", searches={SEARCH: "Taiwan"}, at=NOW
    )

    (source,) = uow.store.sources.values()
    assert created == 1
    assert (source.kind, source.endpoint, source.market) == ("himalayas", SEARCH, "Taiwan")
    assert (source.origin, source.status) == (SourceOrigin.DEMAND, SourceStatus.ACTIVE)
    assert source.company_id is None and source.last_requested_at == NOW
    assert not hasattr(source, "owner_id")


async def test_two_requests_for_the_same_search_share_one_source() -> None:
    uow = FakeMarketUnitOfWork()
    market = _service(uow)
    await market.request_searches(kind="himalayas", searches={SEARCH: "Taiwan"}, at=NOW)

    later = NOW + timedelta(days=3)
    created = await market.request_searches(kind="himalayas", searches={SEARCH: "Taiwan"}, at=later)

    (source,) = uow.store.sources.values()
    assert created == 0 and source.last_requested_at == later


async def test_a_new_search_is_crawled_before_the_weekly_run_and_only_once() -> None:
    uow = FakeMarketUnitOfWork()
    ingest = CrawlIngest(uow)
    board = _source(uow)
    await ingest.record_crawl(board.id, [])
    await _service(uow).request_searches(kind="himalayas", searches={SEARCH: "Taiwan"}, at=NOW)

    (new,) = await ingest.new_sources()
    assert (new.endpoint, new.market, new.company_id) == (SEARCH, "Taiwan", None)

    await ingest.record_search_crawl(new.id, [], error="board returned 429")

    # A search that failed waits for the weekly run like any other source.
    assert await ingest.new_sources() == []
    assert len(await ingest.due_sources()) == 2


async def test_a_search_crawl_is_stored_without_announcing_each_search() -> None:
    uow = FakeMarketUnitOfWork()
    ingest = CrawlIngest(uow)
    await _service(uow).request_searches(kind="himalayas", searches={SEARCH: "Taiwan"}, at=NOW)
    (search,) = await ingest.new_sources()

    first = await ingest.record_search_crawl(search.id, [_remote("Data"), _remote("ML")])
    same = await ingest.record_search_crawl(search.id, [_remote("Data"), _remote("ML")])
    fewer = await ingest.record_search_crawl(search.id, [_remote("Data")])

    assert first == (2, 0, True)
    # The same openings again are no reason to rebuild anybody's role map.
    assert same == (2, 0, False)
    assert fewer == (1, 1, True)
    assert uow.store.events == []


async def test_an_opening_that_comes_back_counts_as_a_change() -> None:
    uow = FakeMarketUnitOfWork()
    ingest = CrawlIngest(uow)
    await _service(uow).request_searches(kind="himalayas", searches={SEARCH: "Taiwan"}, at=NOW)
    (search,) = await ingest.new_sources()
    await ingest.record_search_crawl(search.id, [_remote("Data")])
    await ingest.record_search_crawl(search.id, [])

    assert await ingest.record_search_crawl(search.id, [_remote("Data")]) == (1, 0, True)


async def test_a_place_is_announced_once_however_many_of_its_searches_changed() -> None:
    uow = FakeMarketUnitOfWork()

    await CrawlIngest(uow).announce_markets(["Taiwan", "Singapore", "Taiwan"])

    assert uow.store.events == [
        PostingsChanged(company_id=None, market="Singapore", seen=0, expired=0),
        PostingsChanged(company_id=None, market="Taiwan", seen=0, expired=0),
    ]


async def test_a_search_nobody_asks_for_any_more_is_retired_with_what_it_found() -> None:
    uow = FakeMarketUnitOfWork()
    market, ingest = _service(uow), CrawlIngest(uow)
    wanted = SEARCH.replace("data", "platform")
    await market.request_searches(kind="himalayas", searches={SEARCH: "Taiwan"}, at=NOW)
    await market.request_searches(
        kind="himalayas", searches={wanted: "Taiwan"}, at=NOW + timedelta(weeks=7)
    )
    idle = next(s for s in uow.store.sources.values() if s.endpoint == SEARCH)
    await ingest.record_search_crawl(idle.id, [_remote("Data")])
    board = _source(uow)

    retired = await ingest.retire_idle_searches(NOW + timedelta(weeks=8, days=1))

    assert retired == 1
    assert uow.store.sources[idle.id].status is SourceStatus.RETIRED
    # Nothing would ever expire its postings again, so they are expired now.
    assert [p.status for p in uow.store.postings.values()] == [PostingStatus.EXPIRED]
    assert uow.store.events[-1] == PostingsChanged(
        company_id=None, market="Taiwan", seen=0, expired=1
    )
    # A search still asked for, and a company's board, are left alone.
    active = {s.endpoint for s in uow.store.sources.values() if s.status is SourceStatus.ACTIVE}
    assert active == {wanted, board.endpoint}


async def test_a_retired_search_asked_for_again_is_crawled_afresh() -> None:
    uow = FakeMarketUnitOfWork()
    market, ingest = _service(uow), CrawlIngest(uow)
    await market.request_searches(kind="himalayas", searches={SEARCH: "Taiwan"}, at=NOW)
    (search,) = await ingest.new_sources()
    await ingest.record_search_crawl(search.id, [])
    await ingest.retire_idle_searches(NOW + timedelta(weeks=9))

    await market.request_searches(
        kind="himalayas", searches={SEARCH: "Taiwan"}, at=NOW + timedelta(weeks=10)
    )

    assert [s.id for s in await ingest.new_sources()] == [search.id]


async def test_an_opening_found_through_a_job_site_is_credited_wherever_it_is_read() -> None:
    uow = FakeMarketUnitOfWork()
    market, ingest = _service(uow), CrawlIngest(uow)
    await market.set_target_locations(OWNER, ["Taiwan"])
    await market.request_searches(kind="himalayas", searches={SEARCH: "Taiwan"}, at=NOW)
    (search,) = await ingest.new_sources()
    found = replace(
        _remote("Data", "Remote, Worldwide"),
        url="https://himalayas.app/companies/acme/jobs/data",
    )
    await ingest.record_search_crawl(search.id, [found])
    board = _source(uow)
    await ingest.record_crawl(board.id, [replace(_posting("Backend"), location="Taipei, Taiwan")])

    credits = {p.title: p.credited_to for p in await market.postings_in_scope(OWNER)}

    # The worldwide opening is in scope for Taiwan, and says where it came from.
    assert credits == {"Data": "Himalayas", "Backend": None}
