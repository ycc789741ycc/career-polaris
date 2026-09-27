"""A crawl run goes on past a board whose postings cannot be stored."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from advisor.market import CrawlSourceView, NormalizedPosting, SourceKind
from advisor.market.crawling import run


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
