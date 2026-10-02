"""What becomes of a build request (ADR 0027): queued once it has started, or
one check on the market scheduled once it waits for it. No job runner."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from wiring import queue

OWNER = uuid.UUID("00000000-0000-0000-0000-000000000001")


@pytest.fixture
def deferred(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def enqueue(name: str, **kwargs: Any) -> None:
        calls.append({"name": name, **kwargs})

    async def enqueue_later(name: str, *, seconds: int, **kwargs: Any) -> None:
        calls.append({"name": name, "seconds": seconds, **kwargs})

    monkeypatch.setattr(queue, "enqueue", enqueue)
    monkeypatch.setattr(queue, "enqueue_later", enqueue_later)
    monkeypatch.setattr(queue, "get_settings", lambda: SimpleNamespace(crawl_due_poll_seconds=15))
    return calls


def _requested(*, should_queue: bool, should_await_market: bool) -> Any:
    return SimpleNamespace(
        build=SimpleNamespace(id=uuid.UUID(int=7)),
        should_queue=should_queue,
        should_await_market=should_await_market,
    )


async def test_a_started_build_is_queued(deferred: list[dict[str, Any]]) -> None:
    await queue.queue_build(OWNER, _requested(should_queue=True, should_await_market=False))

    assert deferred == [
        {"name": "rolemap.recluster", "owner_id": str(OWNER), "build_id": str(uuid.UUID(int=7))}
    ]


async def test_a_build_waiting_for_the_market_gets_one_check_after_the_poll(
    deferred: list[dict[str, Any]],
) -> None:
    await queue.queue_build(OWNER, _requested(should_queue=False, should_await_market=True))

    assert deferred == [
        {
            "name": "rolemap.await_market",
            "seconds": 15,
            "owner_id": str(OWNER),
            "build_id": str(uuid.UUID(int=7)),
        }
    ]


async def test_a_request_that_joined_an_open_build_schedules_nothing(
    deferred: list[dict[str, Any]],
) -> None:
    await queue.queue_build(OWNER, _requested(should_queue=False, should_await_market=False))

    assert deferred == []
