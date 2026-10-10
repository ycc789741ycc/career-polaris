"""Google Generative Language API."""

from __future__ import annotations

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


class GoogleProvider(Provider):
    name = "google"
    default_base_url = "https://generativelanguage.googleapis.com/v1beta"

    async def complete(self, client: GuardedClient, request: Request) -> Completion:
        body: dict[str, Any] = {
            "systemInstruction": {"parts": [{"text": request.system}]},
            "contents": [{"role": "user", "parts": [{"text": request.user}]}],
            "generationConfig": {"maxOutputTokens": request.max_output_tokens},
        }
        response = await client.request(
            "POST",
            f"{request.base_url.rstrip('/')}/models/{request.model}:generateContent",
            headers={
                "content-type": "application/json",
                "x-goog-api-key": request.api_key,
            },
            json=body,
        )
        _raise_for_status(response.status_code, response.text)
        payload = response.json()

        candidates = payload.get("candidates") or [{}]
        parts = (candidates[0].get("content") or {}).get("parts") or []
        text = "".join(str(part.get("text", "")) for part in parts)
        usage = payload.get("usageMetadata", {})
        return Completion(
            text=text,
            input_tokens=int(usage.get("promptTokenCount", 0)),
            output_tokens=int(usage.get("candidatesTokenCount", 0)),
            model=request.model,
        )

    async def stream(self, client: GuardedClient, request: Request) -> AsyncGenerator[StreamEvent]:
        """Google's streaming wire format differs enough to be its own job.

        Until it is built, the whole reply is yielded as one piece, with the
        usage Google reported for it.
        """
        completion = await self.complete(client, request)
        yield TextDelta(completion.text)
        yield Usage(
            input_tokens=completion.input_tokens,
            output_tokens=completion.output_tokens,
            model=completion.model,
        )
