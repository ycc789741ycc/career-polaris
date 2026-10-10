"""Anthropic Messages API."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Any

from kernel.ai_gateway.providers.base import (
    Completion,
    Provider,
    Request,
    StreamEvent,
    TextDelta,
    Usage,
)
from kernel.errors import CredentialFailedError, ProviderUnavailableError
from kernel.fetch import GuardedClient

API_VERSION = "2023-06-01"


class AnthropicProvider(Provider):
    name = "anthropic"
    default_base_url = "https://api.anthropic.com"

    def _headers(self, request: Request) -> dict[str, str]:
        return {
            "x-api-key": request.api_key,
            "anthropic-version": API_VERSION,
            "content-type": "application/json",
        }

    def _body(self, request: Request, *, stream: bool) -> dict[str, Any]:
        return {
            "model": request.model,
            "max_tokens": request.max_output_tokens,
            "system": request.system,
            "messages": [{"role": "user", "content": request.user}],
            "stream": stream,
        }

    async def complete(self, client: GuardedClient, request: Request) -> Completion:
        response = await client.request(
            "POST",
            f"{request.base_url.rstrip('/')}/v1/messages",
            headers=self._headers(request),
            json=self._body(request, stream=False),
        )
        _raise_for_status(response.status_code, response.text)
        payload = response.json()

        text = "".join(
            block.get("text", "")
            for block in payload.get("content", [])
            if block.get("type") == "text"
        )
        usage = payload.get("usage", {})
        return Completion(
            text=text,
            input_tokens=int(usage.get("input_tokens", 0)),
            output_tokens=int(usage.get("output_tokens", 0)),
            model=str(payload.get("model", request.model)),
        )

    async def stream(self, client: GuardedClient, request: Request) -> AsyncGenerator[StreamEvent]:
        """Text as it arrives, and the usage Anthropic reports: the input
        tokens with ``message_start``, the output so far with each
        ``message_delta``."""
        async with client.stream(
            "POST",
            f"{request.base_url.rstrip('/')}/v1/messages",
            headers=self._headers(request),
            json=self._body(request, stream=True),
        ) as response:
            if response.status_code >= 400:
                _raise_for_status(response.status_code, await response.get_text())
            model = request.model
            input_tokens = 0
            async for line in response.get_lines():
                if not line.startswith("data: "):
                    continue
                try:
                    event = json.loads(line.removeprefix("data: "))
                except ValueError:
                    continue
                kind = event.get("type")
                if kind == "content_block_delta":
                    piece = event.get("delta", {}).get("text")
                    if piece:
                        yield TextDelta(str(piece))
                elif kind == "message_start":
                    message = event.get("message") or {}
                    model = str(message.get("model") or model)
                    usage = message.get("usage") or {}
                    input_tokens = int(usage.get("input_tokens", 0))
                    yield Usage(
                        input_tokens=input_tokens,
                        output_tokens=int(usage.get("output_tokens", 0)),
                        model=model,
                    )
                elif kind == "message_delta":
                    usage = event.get("usage") or {}
                    if "output_tokens" in usage:
                        yield Usage(
                            input_tokens=int(usage.get("input_tokens") or input_tokens),
                            output_tokens=int(usage["output_tokens"]),
                            model=model,
                        )


def _raise_for_status(status: int, body: str) -> None:
    if status in (401, 403):
        raise CredentialFailedError("the provider rejected this API key", status=status)
    if status == 429:
        raise CredentialFailedError("the provider rate-limited this key", status=status)
    if status >= 400:
        # The body may echo user content, so it is not passed to the client.
        raise ProviderUnavailableError(f"provider returned {status}", status=status)
