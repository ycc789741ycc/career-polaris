"""A crawl run fetches only what builds are waiting for (ADR 0027): it goes on
past a board it cannot reach or whose postings cannot be stored, leaves a
source on a host that asked us to stop due, and marks what it fetched only
once its postings are embedded."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from advisor.market import CrawlSourceView, NormalizedPosting, SourceKind
from advisor.market.crawling import discovery, run
from advisor.market.crawling.politeness import HostGuard, RateLimiter, RobotsCache
from kernel.errors import BlockedAddressError, RateLimitedError, UpstreamFailedError
from kernel.fetch import GuardedClient, ssrf

NOW = datetime(2026, 10, 2, 9, 0, tzinfo=UTC)


class FakeIngest:
    """Records what a run stores, embeds and marks fetched, in order."""

    def __init__(self, due: list[CrawlSourceView], *, failing: uuid.UUID | None = None) -> None:
        self.due = due
        self.failing = failing
        self.recorded: list[tuple[uuid.UUID, int, str | None]] = []
        self.log: list[tuple[str, Any]] = []

    async def due_sources(self) -> list[CrawlSourceView]:
        return self.due

    async def record_crawl(
        self, source_id: uuid.UUID, postings: list[NormalizedPosting], *, error: str | None = None
    ) -> tuple[int, int]:
        if source_id == self.failing and error is None:
            raise RuntimeError("value too long for type character varying(255)")
        self.recorded.append((source_id, len(postings), error))
        self.log.append(("record", source_id))
        return (len(postings), 0)

    async def postings_needing_embeddings(self, model_name: str, limit: int) -> list[Any]:
        self.log.append(("embed", None))
        return []

    async def mark_fetched(self, source_ids: Any) -> None:
        self.log.append(("fetched", list(source_ids)))


def _politeness(**guard: Any) -> run.CrawlPoliteness:
    return run.CrawlPoliteness(
        robots=RobotsCache("test"),
        limiter=RateLimiter(per_second=0),
        guard=HostGuard(max_per_day=guard.get("max_per_day", 100), clock=lambda: NOW),
    )


_RUN: dict[str, Any] = {"user_agent": "test", "timeout_seconds": 1, "embedding_model": "m"}


def _source(name: str, *, host: str = "boards.test") -> CrawlSourceView:
    return CrawlSourceView(
        id=uuid.uuid4(),
        kind="greenhouse",
        endpoint=f"https://{host}/{name}",
        company_id=uuid.uuid4(),
        company_name=name,
        market=None,
    )


async def _one_posting(client: Any, source: CrawlSourceView, **_: Any) -> list[NormalizedPosting]:
    return [
        NormalizedPosting(
            external_id=source.endpoint,
            company_name=source.company_name or "Acme",
            title="Engineer",
            location="Berlin",
            description="Build things.",
            url=source.endpoint,
            source_kind=SourceKind.ATS_BOARD,
            posted_on=None,
            salary=None,
        )
    ]


async def test_what_a_run_fetched_is_marked_only_after_it_is_embedded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first, second = _source("Acme"), _source("Kestrel")
    ingest = FakeIngest([first, second])
    monkeypatch.setattr(run, "fetch_source", _one_posting)

    await run.crawl_due(ingest, _politeness(), **_RUN)  # type: ignore[arg-type]

    assert ingest.log == [
        ("record", first.id),
        ("record", second.id),
        ("embed", None),
        ("fetched", [first.id, second.id]),
    ]


async def test_a_run_with_nothing_due_fetches_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    async def never(*_: Any, **__: Any) -> list[NormalizedPosting]:
        raise AssertionError("nothing is due, so nothing is fetched")

    monkeypatch.setattr(run, "fetch_source", never)
    ingest = FakeIngest([])

    assert await run.crawl_due(ingest, _politeness(), **_RUN) == []  # type: ignore[arg-type]
    assert ingest.log == []


async def test_one_board_that_cannot_be_stored_does_not_stop_the_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bad, good = _source("Datadog"), _source("Acme")
    ingest = FakeIngest([bad, good], failing=bad.id)
    monkeypatch.setattr(run, "fetch_source", _one_posting)

    outcomes = await run.crawl_due(ingest, _politeness(), **_RUN)  # type: ignore[arg-type]

    assert [(o.source_id, o.error is None) for o in outcomes] == [(bad.id, False), (good.id, True)]
    assert (bad.id, 0, "storing postings failed: RuntimeError") in ingest.recorded
    assert (good.id, 1, None) in ingest.recorded
    # A failure counts as fetched: the builds waiting for it go on without it.
    assert ingest.log[-1] == ("fetched", [bad.id, good.id])


def _resolve(host: str, port: int) -> list[str]:
    """No DNS in a unit test: one host is gone, the other now points inside."""
    if host == "gone.test":
        raise BlockedAddressError(f"host {host!r} could not be resolved", host=host)
    return ["10.0.0.7"]


async def test_a_board_whose_host_is_unreachable_is_recorded_and_the_run_goes_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gone = _source("acme", host="gone.test")
    private = _source("kestrel", host="inside.test")
    ingest = FakeIngest([gone, private])
    monkeypatch.setattr(ssrf, "resolve_addresses", _resolve)

    outcomes = await run.crawl_due(ingest, _politeness(), **_RUN)  # type: ignore[arg-type]

    assert [o.source_id for o in outcomes] == [gone.id, private.id]
    assert ingest.recorded == [
        (gone.id, 0, "host 'gone.test' could not be resolved"),
        (private.id, 0, "inside.test resolves to a private address (10.0.0.7)"),
    ]


async def test_a_source_on_a_host_that_asked_us_to_stop_stays_due(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paused, fine = _source("data", host="himalayas.app"), _source("Acme")
    ingest = FakeIngest([paused, fine])

    async def fetched(client: Any, source: CrawlSourceView, **kw: Any) -> list[NormalizedPosting]:
        if source.id == paused.id:
            raise RateLimitedError("host paused after refusing us", host="himalayas.app")
        return await _one_posting(client, source, **kw)

    monkeypatch.setattr(run, "fetch_source", fetched)

    outcomes = await run.crawl_due(ingest, _politeness(), **_RUN)  # type: ignore[arg-type]

    # Not recorded and not marked fetched: tried again once the host may be asked.
    assert [o.source_id for o in outcomes] == [fine.id]
    assert ingest.log[-1] == ("fetched", [fine.id])


# --- fetching one source, politely -------------------------------------------


class _Response:
    def __init__(self, status: int, text: str = "[]", headers: dict[str, str] | None = None):
        self.status_code = status
        self.text = text
        self.headers = headers or {}

    def json(self) -> Any:
        return {"jobs": []}


class FakeClient:
    """Answers robots.txt with nothing disallowed, and each endpoint with the
    next status queued for it."""

    def __init__(self, answers: list[_Response]) -> None:
        self.answers = answers
        self.requested: list[str] = []

    async def request(self, method: str, url: str, **_: Any) -> _Response:
        self.requested.append(url)
        if url.endswith("/robots.txt"):
            return _Response(404, "")
        return self.answers.pop(0)


def _search() -> CrawlSourceView:
    return CrawlSourceView(
        id=uuid.uuid4(),
        kind="himalayas",
        endpoint="https://himalayas.app/jobs/api/search?q=data&country=TW",
        company_id=None,
        company_name=None,
        market="Taiwan",
    )


async def test_a_refusal_pauses_the_host_and_the_next_fetch_never_leaves() -> None:
    politeness = _politeness()
    client = FakeClient([_Response(429, headers={"retry-after": "120"})])
    search = _search()

    with pytest.raises(RateLimitedError):
        await run.fetch_source(
            client,  # type: ignore[arg-type]
            search,
            robots=politeness.robots,
            limiter=politeness.limiter,
            guard=politeness.guard,
        )
    with pytest.raises(RateLimitedError):
        await run.fetch_source(
            client,  # type: ignore[arg-type]
            search,
            robots=politeness.robots,
            limiter=politeness.limiter,
            guard=politeness.guard,
        )

    # robots.txt once, the search once: the second attempt was held back here.
    assert client.requested == [
        "https://himalayas.app/robots.txt",
        "https://himalayas.app/jobs/api/search?q=data&country=TW",
    ]


async def test_robots_txt_is_read_once_across_runs() -> None:
    politeness = _politeness()
    client = FakeClient([_Response(200, '{"jobs": []}'), _Response(200, '{"jobs": []}')])

    for _ in range(2):
        await run.fetch_source(
            client,  # type: ignore[arg-type]
            _search(),
            robots=politeness.robots,
            limiter=politeness.limiter,
            guard=politeness.guard,
        )

    assert client.requested.count("https://himalayas.app/robots.txt") == 1


async def test_a_host_past_its_daily_ceiling_is_not_asked_again_that_day() -> None:
    # robots.txt and one search: two requests, the whole day's allowance.
    politeness = _politeness(max_per_day=2)
    client = FakeClient([_Response(200, '{"jobs": []}')])
    kwargs = {"robots": politeness.robots, "limiter": politeness.limiter}

    await run.fetch_source(client, _search(), guard=politeness.guard, **kwargs)  # type: ignore[arg-type]

    with pytest.raises(RateLimitedError):
        await run.fetch_source(client, _search(), guard=politeness.guard, **kwargs)  # type: ignore[arg-type]
    assert len(client.requested) == 2


async def test_other_failures_are_still_failures() -> None:
    politeness = _politeness()
    client = FakeClient([_Response(500)])

    with pytest.raises(UpstreamFailedError):
        await run.fetch_source(
            client,  # type: ignore[arg-type]
            _search(),
            robots=politeness.robots,
            limiter=politeness.limiter,
            guard=politeness.guard,
        )


async def test_discovery_treats_an_unreachable_board_as_no_board(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ssrf, "resolve_addresses", _resolve)

    async with GuardedClient(timeout_seconds=1, user_agent="test") as client:
        found = await discovery.discover_board(
            client, "Acme", url="https://gone.test/careers", user_agent="test"
        )

    assert found is None
