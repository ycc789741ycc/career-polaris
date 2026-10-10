"""The only outbound HTTP client in the system.

Redirects are followed by hand so every hop is re-validated — a 302 into
``169.254.169.254`` is the usual way an SSRF guard that only checks the first
URL gets bypassed.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx

from kernel.errors import BlockedAddressError, UpstreamFailedError
from kernel.fetch.ssrf import assert_public_url

MAX_REDIRECTS = 5


class StreamedResponse:
    """A response read as it arrives, never past the client's size limit."""

    def __init__(self, response: httpx.Response, *, url: str, max_bytes: int) -> None:
        self._response = response
        self._url = url
        self._max_bytes = max_bytes
        self._read = 0

    @property
    def status_code(self) -> int:
        return self._response.status_code

    def _count(self, size: int) -> None:
        self._read += size
        if self._read > self._max_bytes:
            raise UpstreamFailedError(
                "response exceeded the size limit", url=self._url, limit=self._max_bytes
            )

    async def get_text(self) -> str:
        """The whole body, for an error reply."""
        parts: list[str] = []
        async for line in self.get_lines():
            parts.append(line)
        return "\n".join(parts)

    async def get_lines(self) -> AsyncIterator[str]:
        try:
            async for line in self._response.aiter_lines():
                self._count(len(line.encode()) + 1)
                yield line
        except httpx.HTTPError as exc:
            raise UpstreamFailedError(f"reading from {self._url} failed", url=self._url) from exc


class GuardedClient:
    """An ``httpx.AsyncClient`` that refuses non-public destinations."""

    def __init__(
        self,
        *,
        timeout_seconds: float,
        user_agent: str,
        max_response_bytes: int = 10_000_000,
    ) -> None:
        self._max_response_bytes = max_response_bytes
        self._client = httpx.AsyncClient(
            timeout=timeout_seconds,
            follow_redirects=False,
            headers={"User-Agent": user_agent},
        )

    async def __aenter__(self) -> GuardedClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            assert_public_url(current)
            try:
                response = await self._client.request(method, current, **kwargs)
            except httpx.HTTPError as exc:
                raise UpstreamFailedError(f"request to {current} failed", url=current) from exc

            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    raise UpstreamFailedError("redirect without a Location header", url=current)
                current = str(httpx.URL(current).join(location))
                # Only the first request may carry a body or auth header.
                kwargs.pop("content", None)
                kwargs.pop("json", None)
                kwargs.pop("data", None)
                continue

            if len(response.content) > self._max_response_bytes:
                raise UpstreamFailedError(
                    "response exceeded the size limit",
                    url=current,
                    limit=self._max_response_bytes,
                )
            return response

        raise BlockedAddressError(f"too many redirects starting at {url}", url=url)

    @asynccontextmanager
    async def stream(self, method: str, url: str, **kwargs: Any) -> AsyncIterator[StreamedResponse]:
        """Like :meth:`request`, but the body is read as it arrives.

        Every hop is checked as in :meth:`request`. Leaving the block closes
        the connection, which is how a caller stops a reply mid-way.
        """
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            assert_public_url(current)
            request = self._client.build_request(method, current, **kwargs)
            try:
                response = await self._client.send(request, stream=True)
            except httpx.HTTPError as exc:
                raise UpstreamFailedError(f"request to {current} failed", url=current) from exc

            if response.is_redirect:
                location = response.headers.get("location")
                await response.aclose()
                if not location:
                    raise UpstreamFailedError("redirect without a Location header", url=current)
                current = str(httpx.URL(current).join(location))
                # Only the first request may carry a body or auth header.
                kwargs.pop("content", None)
                kwargs.pop("json", None)
                kwargs.pop("data", None)
                continue

            try:
                yield StreamedResponse(response, url=current, max_bytes=self._max_response_bytes)
            finally:
                await response.aclose()
            return

        raise BlockedAddressError(f"too many redirects starting at {url}", url=url)

    async def get_json(self, url: str, **kwargs: Any) -> Any:
        response = await self.request("GET", url, **kwargs)
        if response.status_code >= 400:
            raise UpstreamFailedError(
                f"upstream returned {response.status_code}",
                url=url,
                status=response.status_code,
            )
        try:
            return response.json()
        except ValueError as exc:
            raise UpstreamFailedError("upstream returned invalid JSON", url=url) from exc
