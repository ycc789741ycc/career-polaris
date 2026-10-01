"""The market's worker jobs against in-memory storage: no database, no network."""

from __future__ import annotations

from types import SimpleNamespace

from advisor.market import MarketService, jobs
from advisor.market.domain import SourceOrigin
from tests.unit.advisor.market.fakes import FakeMarketUnitOfWork


def _deps(uow: FakeMarketUnitOfWork) -> SimpleNamespace:
    return SimpleNamespace(market=MarketService(uow))


async def test_each_title_is_searched_in_each_place_a_search_covers() -> None:
    uow = FakeMarketUnitOfWork()

    await jobs.request_searches(
        _deps(uow),
        titles=["Data Engineer", "Platform Engineer"],
        locations=["Taiwan", "Remote", "Taipei"],
    )

    searches = {(s.endpoint.split("?")[1], s.market) for s in uow.store.sources.values()}
    assert searches == {
        ("q=data%20engineer&country=TW", "Taiwan"),
        ("q=platform%20engineer&country=TW", "Taiwan"),
        ("q=data%20engineer&worldwide=true", "Remote"),
        ("q=platform%20engineer&worldwide=true", "Remote"),
    }
    assert {s.kind for s in uow.store.sources.values()} == {"himalayas"}
    assert {s.origin for s in uow.store.sources.values()} == {SourceOrigin.DEMAND}


async def test_two_ways_of_naming_a_place_are_one_search() -> None:
    uow = FakeMarketUnitOfWork()

    await jobs.request_searches(
        _deps(uow), titles=["Data Engineer"], locations=["Taiwan", "Remote Taiwan"]
    )

    assert len(uow.store.sources) == 1


async def test_a_place_no_search_covers_adds_no_source() -> None:
    uow = FakeMarketUnitOfWork()

    await jobs.request_searches(_deps(uow), titles=["Data Engineer"], locations=["Taipei"])

    assert uow.store.sources == {}


async def test_nothing_about_the_user_reaches_the_sources_a_request_leaves() -> None:
    """The job is handed titles and places only, so it has nothing else to store."""
    uow = FakeMarketUnitOfWork()

    await jobs.request_searches(_deps(uow), titles=["Data Engineer"], locations=["Taiwan"])

    (source,) = uow.store.sources.values()
    assert source.company_id is None
    assert "data%20engineer" in source.endpoint and "TW" in source.endpoint
    assert uow.store.events == []
