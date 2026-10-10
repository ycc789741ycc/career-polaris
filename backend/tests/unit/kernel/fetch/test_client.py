"""A streamed response keeps the guard's rules: every hop checked, never past
the size limit, and closed when the reader leaves."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable

import httpx
import pytest

from kernel.errors import BlockedAddressError, UpstreamFailedError
from kernel.fetch import GuardedClient, client, ssrf

ADDRESSES = {"llm.example.com": ["93.184.216.34"], "internal.example.com": ["10.0.0.5"]}


@pytest.fixture(autouse=True)
def resolver(monkeypatch: pytest.MonkeyPatch) -> None:
    """Resolve from a table, so the test needs no network."""

    def check(url: str) -> None:
        ssrf.assert_public_url(url, resolver=lambda host, port: ADDRESSES.get(host, []))

    monkeypatch.setattr(client, "assert_public_url", check)


def _guarded(handler: Callable[[httpx.Request], httpx.Response], **kwargs: int) -> GuardedClient:
    guarded = GuardedClient(timeout_seconds=5, user_agent="test", **kwargs)
    guarded._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return guarded


class _Body(httpx.AsyncByteStream):
    """A body that remembers whether it was closed."""

    def __init__(self, lines: list[bytes]) -> None:
        self.lines = lines
        self.is_closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for line in self.lines:
            yield line

    async def aclose(self) -> None:
        self.is_closed = True


async def test_lines_arrive_as_they_are_read() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"data: one\n\ndata: two\n")

    async with (
        _guarded(handler) as guarded,
        guarded.stream("POST", "https://llm.example.com/v1/messages") as response,
    ):
        assert response.status_code == 200
        lines = [line async for line in response.get_lines()]

    assert lines == ["data: one", "", "data: two"]


async def test_a_body_past_the_limit_is_refused_while_it_is_read() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 100 + b"\n" + b"y" * 100 + b"\n")

    async with (
        _guarded(handler, max_response_bytes=150) as guarded,
        guarded.stream("POST", "https://llm.example.com/v1/messages") as response,
    ):
        with pytest.raises(UpstreamFailedError, match="size limit"):
            async for _ in response.get_lines():
                pass


async def test_a_redirect_into_a_private_network_is_refused() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://internal.example.com/x"})

    async with _guarded(handler) as guarded:
        with pytest.raises(BlockedAddressError):
            async with guarded.stream("POST", "https://llm.example.com/v1/messages"):
                pass


async def test_leaving_the_block_closes_the_connection() -> None:
    body = _Body([b"data: one\n", b"data: two\n", b"data: three\n"])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=body)

    async with _guarded(handler) as guarded:
        async with guarded.stream("POST", "https://llm.example.com/v1/messages") as response:
            async for _ in response.get_lines():
                break

    assert body.is_closed
