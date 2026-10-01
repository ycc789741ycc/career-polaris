"""A crawl run goes on past a board it cannot reach or whose postings cannot be
stored, and announces a searched place once, not once per search (ADR 0025)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from advisor.market import CrawlSourceView, NormalizedPosting, SourceKind
from advisor.market.crawling import discovery, run
from kernel.errors import BlockedAddressError
from kernel.fetch import GuardedClient, ssrf


class FakeIngest:
    def __init__(self, sources: list[CrawlSourceView], failing: uuid.UUID) -> None:
        self.sources = sources
        self.failing = failing
        self.recorded: list[tuple[uuid.UUID, int, str | None]] = []

    async def due_sources(self) -> list[CrawlSourceView]:
        return self.sources

    async def record_crawl(
        self, source_id: uuid.UUID, postings: list[NormalizedPosting], *, error: str | None = None
    ) -> tuple[int, int]:
        if source_id == self.failing and error is None:
            raise RuntimeError("value too long for type character varying(255)")
        self.recorded.append((source_id, len(postings), error))
        return (len(postings), 0)

    async def postings_needing_embeddings(self, model_name: str, limit: int) -> list[Any]:
        return []


class SearchIngest:
    """Records what a run stores and announces, and in which order."""

    def __init__(
        self,
        due: list[CrawlSourceView],
        new: list[CrawlSourceView] | None = None,
        unchanged: set[uuid.UUID] | None = None,
    ) -> None:
        self.due = due
        self.new = new or []
        self.unchanged = unchanged or set()
        self.log: list[tuple[str, Any]] = []

    async def due_sources(self) -> list[CrawlSourceView]:
        return self.due

    async def new_sources(self) -> list[CrawlSourceView]:
        return self.new

    async def record_crawl(
        self, source_id: uuid.UUID, postings: list[NormalizedPosting], *, error: str | None = None
    ) -> tuple[int, int]:
        self.log.append(("board" if error is None else "failed", source_id))
        return (len(postings), 0)

    async def record_search_crawl(
        self, source_id: uuid.UUID, postings: list[NormalizedPosting], *, error: str | None = None
    ) -> tuple[int, int, bool]:
        self.log.append(("search", source_id))
        return (len(postings), 0, source_id not in self.unchanged)

    async def postings_needing_embeddings(self, model_name: str, limit: int) -> list[Any]:
        self.log.append(("embed", None))
        return []

    async def announce_markets(self, markets: Any) -> None:
        self.log.append(("announce", sorted(markets)))


def _search(title: str, market: str) -> CrawlSourceView:
    return CrawlSourceView(
        id=uuid.uuid4(),
        kind="himalayas",
        endpoint=f"https://himalayas.app/jobs/api/search?q={title}&country=TW",
        company_id=None,
        company_name=None,
        market=market,
    )


async def _one_posting(client: Any, source: CrawlSourceView, **_: Any) -> list[NormalizedPosting]:
    return [
        NormalizedPosting(
            external_id=source.endpoint,
            company_name="Acme",
            title="Engineer",
            location="Remote, Taiwan",
            description="Build things.",
            url=source.endpoint,
            source_kind=SourceKind.PUBLIC_API,
            posted_on=None,
            salary=None,
        )
    ]


_RUN: dict[str, Any] = {
    "user_agent": "test",
    "timeout_seconds": 1,
    "rate_limit_per_second": 100,
    "embedding_model": "test-model",
}


def _source(name: str) -> CrawlSourceView:
    return CrawlSourceView(
        id=uuid.uuid4(),
        kind="greenhouse",
        endpoint=f"https://boards.test/{name}",
        company_id=uuid.uuid4(),
        company_name=name,
        market=None,
    )


async def test_one_board_that_cannot_be_stored_does_not_stop_the_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bad, good = _source("Datadog"), _source("Acme")
    ingest = FakeIngest([bad, good], failing=bad.id)

    async def fetched(client: Any, source: CrawlSourceView, **_: Any) -> list[NormalizedPosting]:
        return [
            NormalizedPosting(
                external_id="1",
                company_name=source.company_name or "",
                title="Engineer",
                location="Berlin",
                description="Build things.",
                url="https://boards.test/1",
                source_kind=SourceKind.ATS_BOARD,
                posted_on=None,
                salary=None,
            )
        ]

    monkeypatch.setattr(run, "fetch_source", fetched)

    outcomes = await run.crawl_all(
        ingest,  # type: ignore[arg-type]
        user_agent="test",
        timeout_seconds=1,
        rate_limit_per_second=100,
        embedding_model="test-model",
    )

    assert [(o.source_id, o.error is None) for o in outcomes] == [(bad.id, False), (good.id, True)]
    assert (bad.id, 0, "storing postings failed: RuntimeError") in ingest.recorded
    assert (good.id, 1, None) in ingest.recorded


def _resolve(host: str, port: int) -> list[str]:
    """No DNS in a unit test: one host is gone, the other now points inside."""
    if host == "gone.test":
        raise BlockedAddressError(f"host {host!r} could not be resolved", host=host)
    return ["10.0.0.7"]


async def test_a_board_whose_host_is_unreachable_is_recorded_and_the_run_goes_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gone = CrawlSourceView(
        id=uuid.uuid4(),
        kind="greenhouse",
        endpoint="https://gone.test/v1/boards/acme/jobs",
        company_id=None,
        company_name="Acme",
        market=None,
    )
    private = CrawlSourceView(
        id=uuid.uuid4(),
        kind="greenhouse",
        endpoint="https://inside.test/v1/boards/kestrel/jobs",
        company_id=None,
        company_name="Kestrel",
        market=None,
    )
    ingest = FakeIngest([gone, private], failing=uuid.uuid4())
    monkeypatch.setattr(ssrf, "resolve_addresses", _resolve)

    outcomes = await run.crawl_all(
        ingest,  # type: ignore[arg-type]
        user_agent="test",
        timeout_seconds=1,
        rate_limit_per_second=0,
        embedding_model="test-model",
    )

    assert [o.source_id for o in outcomes] == [gone.id, private.id]
    assert ingest.recorded == [
        (gone.id, 0, "host 'gone.test' could not be resolved"),
        (private.id, 0, "inside.test resolves to a private address (10.0.0.7)"),
    ]


async def test_discovery_treats_an_unreachable_board_as_no_board(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ssrf, "resolve_addresses", _resolve)

    async with GuardedClient(timeout_seconds=1, user_agent="test") as client:
        found = await discovery.discover_board(
            client, "Acme", url="https://gone.test/careers", user_agent="test"
        )

    assert found is None


# --- searches of a public job API (ADR 0025) --------------------------------


async def test_a_places_searches_are_announced_once_after_the_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each announcement is a role-map rebuild on somebody's key."""
    taiwan = [_search("data", "Taiwan"), _search("platform", "Taiwan")]
    singapore = _search("data", "Singapore")
    board = _source("Acme")
    ingest = SearchIngest([*taiwan, board, singapore])
    monkeypatch.setattr(run, "fetch_source", _one_posting)

    outcomes = await run.crawl_all(ingest, **_RUN)  # type: ignore[arg-type]

    assert [o.changed_market for o in outcomes] == ["Taiwan", "Taiwan", None, "Singapore"]
    assert [kind for kind, _ in ingest.log] == [
        "search",
        "search",
        "board",
        "search",
        "embed",
        "announce",
    ]
    # After embedding, so the rebuild it starts finds the vectors.
    assert ingest.log[-1] == ("announce", ["Singapore", "Taiwan"])


async def test_a_place_whose_searches_found_nothing_new_is_not_announced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    taiwan = _search("data", "Taiwan")
    ingest = SearchIngest([taiwan], unchanged={taiwan.id})
    monkeypatch.setattr(run, "fetch_source", _one_posting)

    await run.crawl_all(ingest, **_RUN)  # type: ignore[arg-type]

    assert ("announce", ["Taiwan"]) not in ingest.log
    assert all(kind != "announce" for kind, _ in ingest.log)


async def test_between_weekly_runs_only_sources_never_fetched_are_crawled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    known, fresh = _search("data", "Taiwan"), _search("platform", "Taiwan")
    ingest = SearchIngest(due=[known, fresh], new=[fresh])
    monkeypatch.setattr(run, "fetch_source", _one_posting)

    outcomes = await run.crawl_new(ingest, **_RUN)  # type: ignore[arg-type]

    assert [o.source_id for o in outcomes] == [fresh.id]
    assert ingest.log == [("search", fresh.id), ("embed", None), ("announce", ["Taiwan"])]


async def test_a_look_that_finds_no_new_source_does_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ingest = SearchIngest(due=[_search("data", "Taiwan")], new=[])

    async def never(*_: Any, **__: Any) -> list[NormalizedPosting]:
        raise AssertionError("nothing new, so nothing is fetched")

    monkeypatch.setattr(run, "fetch_source", never)

    assert await run.crawl_new(ingest, **_RUN) == []  # type: ignore[arg-type]
    assert ingest.log == []


async def test_a_search_that_is_rate_limited_is_recorded_and_the_run_goes_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kernel.errors import UpstreamFailedError

    limited, fine = _search("data", "Taiwan"), _search("platform", "Taiwan")
    ingest = SearchIngest([limited, fine])

    async def fetched(client: Any, source: CrawlSourceView, **kw: Any) -> list[NormalizedPosting]:
        if source.id == limited.id:
            raise UpstreamFailedError("board returned 429", endpoint=source.endpoint)
        return await _one_posting(client, source, **kw)

    monkeypatch.setattr(run, "fetch_source", fetched)

    outcomes = await run.crawl_all(ingest, **_RUN)  # type: ignore[arg-type]

    assert [o.error for o in outcomes] == ["board returned 429", None]
    assert ingest.log[0] == ("failed", limited.id)
