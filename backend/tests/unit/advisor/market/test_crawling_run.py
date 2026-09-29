"""A crawl run goes on past a board it cannot reach or whose postings cannot be stored."""

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
