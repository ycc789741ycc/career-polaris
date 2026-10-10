"""OpenAI and any OpenAI-compatible endpoint.

This adapter also covers the "Local" provider in the UI: a model the user runs
themselves, reachable at a public URL they control. The SSRF guard still
applies, so it cannot point at our own network.
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Any

from kernel.ai_gateway.providers.anthropic import _raise_for_status
from kernel.ai_gateway.providers.base import (
    Completion,
    Provider,
    Request,
    StreamEvent,
    TextDelta,
    Usage,
)
from kernel.fetch import GuardedClient


class OpenAICompatibleProvider(Provider):
    name = "openai"
    default_base_url = "https://api.openai.com/v1"
    # OpenAI sends a stream's usage in a last chunk only when asked to.
    asks_for_stream_usage = True

    def _headers(self, request: Request) -> dict[str, str]:
        return {
            "authorization": f"Bearer {request.api_key}",
            "content-type": "application/json",
        }

    def _body(self, request: Request, *, stream: bool) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": request.model,
            "max_completion_tokens": request.max_output_tokens,
            "messages": [
                {"role": "system", "content": request.system},
                {"role": "user", "content": request.user},
            ],
            "stream": stream,
        }
        if stream and self.asks_for_stream_usage:
            body["stream_options"] = {"include_usage": True}
        return body

    async def complete(self, client: GuardedClient, request: Request) -> Completion:
        response = await client.request(
            "POST",
            f"{request.base_url.rstrip('/')}/chat/completions",
            headers=self._headers(request),
            json=self._body(request, stream=False),
        )
        _raise_for_status(response.status_code, response.text)
        payload = response.json()

        choices = payload.get("choices") or [{}]
        text = (choices[0].get("message") or {}).get("content") or ""
        usage = payload.get("usage", {})
        return Completion(
            text=str(text),
            input_tokens=int(usage.get("prompt_tokens", 0)),
            output_tokens=int(usage.get("completion_tokens", 0)),
            model=str(payload.get("model", request.model)),
        )

    async def stream(self, client: GuardedClient, request: Request) -> AsyncGenerator[StreamEvent]:
        async with client.stream(
            "POST",
            f"{request.base_url.rstrip('/')}/chat/completions",
            headers=self._headers(request),
            json=self._body(request, stream=True),
        ) as response:
            if response.status_code >= 400:
                _raise_for_status(response.status_code, await response.get_text())
            async for line in response.get_lines():
                if not line.startswith("data: "):
                    continue
                chunk = line.removeprefix("data: ").strip()
                if chunk == "[DONE]":
                    break
                try:
                    event = json.loads(chunk)
                except ValueError:
                    continue
                for choice in event.get("choices") or []:
                    piece = (choice.get("delta") or {}).get("content")
                    if piece:
                        yield TextDelta(str(piece))
                usage = event.get("usage")
                if usage:
                    yield Usage(
                        input_tokens=int(usage.get("prompt_tokens", 0)),
                        output_tokens=int(usage.get("completion_tokens", 0)),
                        model=str(event.get("model") or request.model),
                    )


class LocalProvider(OpenAICompatibleProvider):
    """Same wire format; the user always supplies the base URL."""

    name = "local"
    default_base_url = ""
    # A server of the user's own may refuse a field it does not know, and its
    # calls cost us nothing to estimate.
    asks_for_stream_usage = False
