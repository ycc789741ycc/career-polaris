"""Market use cases against in-memory storage: what they decide, with no database."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from advisor.market import (
    BaselineSource,
    CrawlIngest,
    FreshWindows,
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
    PostingStatus,
    SourceOrigin,
    SourceStatus,
    TargetLocationsChanged,
)
from kernel.errors import NotFoundError, ValidationError
from tests.unit.advisor.market.fakes import FakeMarketUnitOfWork

OWNER = uuid.UUID("00000000-0000-0000-0000-000000000001")
OTHER = uuid.UUID("00000000-0000-0000-0000-000000000002")


WINDOWS = FreshWindows(search=timedelta(hours=72), board=timedelta(hours=24))


def _service(uow: FakeMarketUnitOfWork) -> MarketService:
    return MarketService(uow, windows=WINDOWS)


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
    # Nothing is announced: no market change is resolved to users (ADR 0027).
    assert uow.store.events == []


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


# --- the sources a build needs (ADR 0027) -----------------------------------

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)


def _remote(title: str, location: str = "Remote, Taiwan") -> NormalizedPosting:
    return replace(_posting(title), location=location, source_kind=SourceKind.PUBLIC_API)


def _searches(uow: FakeMarketUnitOfWork) -> list[CrawlSource]:
    return sorted((s for s in uow.store.sources.values() if s.is_search), key=lambda s: s.endpoint)


async def test_a_build_needs_a_search_per_title_and_place_the_baseline_and_named_boards() -> None:
    uow = FakeMarketUnitOfWork()
    baseline = _source(uow, origin=SourceOrigin.BASELINE)
    company = _company(uow)
    named = CrawlSource.board(
        kind="lever",
        endpoint="https://lever.test/beta",
        company_id=company.id,
        origin=SourceOrigin.DEMAND,
    )
    uow.store.sources[named.id] = named

    request = await _service(uow).request_sources(
        titles=["Data Engineer", "ML Engineer"],
        places=["Taiwan", "Remote", "Europe"],
        company_ids=[company.id],
        at=NOW,
    )

    searches = _searches(uow)
    # Two titles in two searchable places; a region adds none (ADR 0026).
    assert len(searches) == 4
    assert {s.market for s in searches} == {"Taiwan", "Remote"}
    assert all(
        s.company_id is None and s.origin is SourceOrigin.DEMAND and not hasattr(s, "owner_id")
        for s in searches
    )
    assert set(request.needed) == {s.id for s in searches} | {baseline.id, named.id}
    # Nothing has been fetched yet, so the build waits for all of it.
    assert set(request.due) == set(request.needed)
    assert all(uow.store.sources[i].due_at == NOW for i in request.needed)


async def test_each_title_is_searched_by_its_words_in_each_place_under_one_name() -> None:
    uow = FakeMarketUnitOfWork()

    await _service(uow).request_sources(
        titles=["Data Engineer", "Platform Engineer"],
        places=["Taiwan", "Remote"],
        company_ids=[],
        at=NOW,
    )

    searches = {(s.endpoint.split("?")[1], s.market) for s in _searches(uow)}
    assert searches == {
        ("q=data%20engineer&country=TW", "Taiwan"),
        ("q=platform%20engineer&country=TW", "Taiwan"),
        ("q=data%20engineer&worldwide=true", "Remote"),
        ("q=platform%20engineer&worldwide=true", "Remote"),
    }
    assert {s.kind for s in _searches(uow)} == {"himalayas"}
    assert uow.store.events == []


async def test_a_fresh_source_is_reused_and_a_stale_one_is_due() -> None:
    uow = FakeMarketUnitOfWork()
    market = _service(uow)
    board = _source(uow, origin=SourceOrigin.BASELINE)
    first = await market.request_sources(
        titles=["Data Engineer"], places=["Taiwan"], company_ids=[], at=NOW
    )
    for source in uow.store.sources.values():
        source.record_fetch(NOW, None)
        source.fetched()

    # A day and a bit later: the board's 24-hour window has passed, the search's
    # 72-hour one has not.
    later = NOW + timedelta(hours=30)
    again = await market.request_sources(
        titles=["Data Engineer"], places=["Taiwan"], company_ids=[], at=later
    )

    assert set(again.needed) == set(first.needed)
    assert again.due == (board.id,)
    (search,) = _searches(uow)
    assert search.last_requested_at == later and search.due_at is None


async def test_two_builds_needing_one_stale_source_wait_on_one_fetch() -> None:
    uow = FakeMarketUnitOfWork()
    market = _service(uow)

    first = await market.request_sources(
        titles=["Data Engineer"], places=["Taiwan"], company_ids=[], at=NOW
    )
    second = await market.request_sources(
        titles=["data engineer"], places=["Taiwan"], company_ids=[], at=NOW + timedelta(minutes=1)
    )

    (search,) = _searches(uow)
    assert first.due == second.due == (search.id,)
    # Still due from the first ask, not pushed back by the second.
    assert search.due_at == NOW


async def test_a_build_with_no_searchable_place_needs_only_boards() -> None:
    uow = FakeMarketUnitOfWork()
    _source(uow, origin=SourceOrigin.BASELINE)

    request = await _service(uow).request_sources(
        titles=["Data Engineer"], places=["Europe"], company_ids=[], at=NOW
    )

    assert _searches(uow) == [] and len(request.needed) == 1


async def test_the_crawler_sees_only_due_sources_and_a_fetch_stops_the_wait() -> None:
    uow = FakeMarketUnitOfWork()
    ingest = CrawlIngest(uow)
    idle = _source(uow)
    request = await _service(uow).request_sources(
        titles=["Data Engineer"], places=["Taiwan"], company_ids=[], at=NOW
    )

    due = await ingest.due_sources()
    assert [s.id for s in due] == list(request.due) and idle.id not in request.due

    await ingest.record_crawl(due[0].id, [], error="board returned 500")
    # Recorded, but still due until the run marks it fetched after embedding.
    assert await _service(uow).pending_sources(request.due) == request.due
    await ingest.mark_fetched([due[0].id])

    assert await ingest.due_sources() == []
    assert await _service(uow).pending_sources(request.due) == ()


async def test_a_search_fetch_replaces_its_list_and_expires_nothing() -> None:
    uow = FakeMarketUnitOfWork()
    market, ingest = _service(uow), CrawlIngest(uow)
    await market.set_target_locations(OWNER, ["Taiwan"])
    await market.request_sources(
        titles=["Data Engineer"], places=["Taiwan"], company_ids=[], at=NOW
    )
    (search,) = _searches(uow)

    first = await ingest.record_crawl(search.id, [_remote("Data"), _remote("ML")])
    second = await ingest.record_crawl(search.id, [_remote("Data")])

    assert (first, second) == ((2, 0), (1, 0))
    # Pushed off the page, not closed: still open, but no longer counted.
    assert {p.status for p in uow.store.postings.values()} == {PostingStatus.OPEN}
    assert [p.title for p in await market.postings_in_scope(OWNER)] == ["Data"]


async def test_a_posting_on_any_current_list_or_board_stays_in_scope() -> None:
    uow = FakeMarketUnitOfWork()
    market, ingest = _service(uow), CrawlIngest(uow)
    await market.set_target_locations(OWNER, ["Taiwan"])
    await market.request_sources(
        titles=["Data Engineer", "Analytics Engineer"], places=["Taiwan"], company_ids=[], at=NOW
    )
    data, analytics = _searches(uow)
    await ingest.record_crawl(data.id, [_remote("Data")])
    await ingest.record_crawl(analytics.id, [_remote("Data")])

    # Gone from the search that saw it last, still on the other one's list.
    await ingest.record_crawl(analytics.id, [])

    assert [p.title for p in await market.postings_in_scope(OWNER)] == ["Data"]


async def test_the_postings_each_title_search_found_best_first() -> None:
    uow = FakeMarketUnitOfWork()
    market, ingest = _service(uow), CrawlIngest(uow)
    await market.request_sources(
        titles=["Data Engineer", "ML Engineer"], places=["Taiwan"], company_ids=[], at=NOW
    )
    data = next(s for s in _searches(uow) if "data" in s.endpoint)
    await ingest.record_crawl(data.id, [_remote("Second"), _remote("First")])
    ids = {p.title: p.id for p in uow.store.postings.values()}

    found = await market.search_results(titles=["Data Engineer", "ML Engineer"], places=["Taiwan"])

    assert found == {"Data Engineer": [ids["Second"], ids["First"]], "ML Engineer": []}


async def test_the_market_a_build_read_is_as_old_as_its_stalest_fetch() -> None:
    uow = FakeMarketUnitOfWork()
    market = _service(uow)
    old, new = _source(uow), _source(uow)
    uow.store.sources[old.id].record_fetch(NOW - timedelta(days=2), None)
    uow.store.sources[new.id].record_fetch(NOW, None)

    assert await market.oldest_fetch([old.id, new.id]) == NOW - timedelta(days=2)
    assert await market.oldest_fetch([]) is None


async def test_a_searchable_place_is_a_country_or_remote() -> None:
    uow = FakeMarketUnitOfWork()
    market = _service(uow)

    await market.set_target_locations(OWNER, ["Europe"])
    assert not await market.has_searchable_place(OWNER)
    await market.set_target_locations(OWNER, ["Europe", "Taiwan"])
    assert await market.has_searchable_place(OWNER)


# --- what nobody asks for (ADR 0027) ----------------------------------------


async def test_a_search_no_build_needs_any_more_is_retired_and_its_list_emptied() -> None:
    uow = FakeMarketUnitOfWork()
    market, ingest = _service(uow), CrawlIngest(uow)
    await market.set_target_locations(OWNER, ["Taiwan"])
    await market.request_sources(
        titles=["Data Engineer"], places=["Taiwan"], company_ids=[], at=NOW
    )
    await market.request_sources(
        titles=["Platform Engineer"], places=["Taiwan"], company_ids=[], at=NOW + timedelta(days=60)
    )
    idle = next(s for s in _searches(uow) if "data" in s.endpoint)
    await ingest.record_crawl(idle.id, [_remote("Data")])
    board = _source(uow)
    board.last_requested_at = NOW

    retired = await ingest.retire_idle_searches(idle_since=NOW + timedelta(days=30))

    assert retired == 1
    assert uow.store.sources[idle.id].status is SourceStatus.RETIRED
    assert uow.store.sources[idle.id].due_at is None
    assert await market.postings_in_scope(OWNER) == []
    # A search still needed, and a company's board, are left alone.
    active = {s.id for s in uow.store.sources.values() if s.status is SourceStatus.ACTIVE}
    assert idle.id not in active and board.id in active


async def test_a_retired_search_needed_again_is_fetched_afresh() -> None:
    uow = FakeMarketUnitOfWork()
    market, ingest = _service(uow), CrawlIngest(uow)
    await market.request_sources(
        titles=["Data Engineer"], places=["Taiwan"], company_ids=[], at=NOW
    )
    (search,) = _searches(uow)
    await ingest.record_crawl(search.id, [])
    await ingest.mark_fetched([search.id])
    await ingest.retire_idle_searches(idle_since=NOW + timedelta(days=1))

    again = await market.request_sources(
        titles=["Data Engineer"], places=["Taiwan"], company_ids=[], at=NOW + timedelta(days=2)
    )

    assert again.due == (search.id,)
    assert uow.store.sources[search.id].status is SourceStatus.ACTIVE


async def test_a_posting_nothing_holds_is_thinned_and_one_held_is_not() -> None:
    uow = FakeMarketUnitOfWork()
    market, ingest = _service(uow), CrawlIngest(uow)
    board = _source(uow)
    await market.request_sources(
        titles=["Data Engineer"], places=["Taiwan"], company_ids=[], at=NOW
    )
    (search,) = _searches(uow)
    await ingest.record_crawl(board.id, [_posting("Closed"), _posting("Open")])
    await ingest.record_crawl(board.id, [_posting("Open")])
    await ingest.record_crawl(search.id, [_remote("Listed"), _remote("Dropped")])
    await ingest.record_crawl(search.id, [_remote("Listed")])
    by_title = {p.title: p for p in uow.store.postings.values()}
    await ingest.store_embeddings("model", {p.id: [0.1] for p in by_title.values()})

    thinned = await ingest.thin_unheld_postings(unseen_since=utc_tomorrow())

    assert thinned == 2
    assert {t for t, p in by_title.items() if p.thinned_at is not None} == {"Closed", "Dropped"}
    assert by_title["Closed"].description == "" and by_title["Open"].description != ""
    assert set(uow.store.embeddings) == {by_title["Open"].id, by_title["Listed"].id}
    # The row stays: a Target that names it still finds it.
    assert len(uow.store.postings) == 4


def utc_tomorrow() -> datetime:
    return datetime.now(UTC) + timedelta(days=1)


async def test_an_opening_found_through_a_job_site_is_credited_wherever_it_is_read() -> None:
    uow = FakeMarketUnitOfWork()
    market, ingest = _service(uow), CrawlIngest(uow)
    await market.set_target_locations(OWNER, ["Taiwan"])
    await market.request_sources(
        titles=["Data Engineer"], places=["Taiwan"], company_ids=[], at=NOW
    )
    (search,) = _searches(uow)
    found = replace(
        _remote("Data", "Remote, Worldwide"),
        url="https://himalayas.app/companies/acme/jobs/data",
    )
    await ingest.record_crawl(search.id, [found])
    board = _source(uow)
    await ingest.record_crawl(board.id, [replace(_posting("Backend"), location="Taipei, Taiwan")])

    credits = {p.title: p.credited_to for p in await market.postings_in_scope(OWNER)}

    # The worldwide opening is in scope for Taiwan, and says where it came from.
    assert credits == {"Data": "Himalayas", "Backend": None}
