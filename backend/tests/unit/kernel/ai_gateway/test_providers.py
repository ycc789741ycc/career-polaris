"""Each adapter's stream yields the text and the usage its provider reported,
read from recorded server-sent events."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from kernel.ai_gateway.providers import (
    AnthropicProvider,
    GoogleProvider,
    LocalProvider,
    OpenAICompatibleProvider,
    Provider,
    Request,
    StreamEvent,
    TextDelta,
    Usage,
)
from kernel.errors import CredentialFailedError
from kernel.fetch import GuardedClient, client, ssrf


@pytest.fixture(autouse=True)
def resolver(monkeypatch: pytest.MonkeyPatch) -> None:
    def check(url: str) -> None:
        ssrf.assert_public_url(url, resolver=lambda host, port: ["93.184.216.34"])

    monkeypatch.setattr(client, "assert_public_url", check)


REQUEST = Request(
    api_key="sk-test",
    model="claude-haiku-4-5",
    base_url="https://llm.example.com",
    system="Return JSON.",
    user="Analyse.",
    max_output_tokens=4_096,
)


def _sse(*events: dict[str, Any]) -> bytes:
    return b"".join(f"data: {json.dumps(event)}\n\n".encode() for event in events)


class _Recorder:
    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self.body = body
        self.sent: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.sent.append(json.loads(request.content))
        return httpx.Response(self.status, content=self.body)


async def _events(provider: Provider, recorder: _Recorder) -> list[StreamEvent]:
    guarded = GuardedClient(timeout_seconds=5, user_agent="test")
    guarded._client = httpx.AsyncClient(transport=httpx.MockTransport(recorder))
    async with guarded:
        return [event async for event in provider.stream(guarded, REQUEST)]


async def test_anthropic_reports_input_first_and_output_at_the_end() -> None:
    recorder = _Recorder(
        200,
        _sse(
            {
                "type": "message_start",
                "message": {
                    "model": "claude-haiku-4-5-20251001",
                    "usage": {"input_tokens": 1_840, "output_tokens": 1},
                },
            },
            {"type": "content_block_delta", "delta": {"type": "text_delta", "text": '{"a": '}},
            {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "1}"}},
            {"type": "message_delta", "usage": {"output_tokens": 612}},
            {"type": "message_stop"},
        ),
    )

    events = await _events(AnthropicProvider(), recorder)

    assert [e.text for e in events if isinstance(e, TextDelta)] == ['{"a": ', "1}"]
    usages = [e for e in events if isinstance(e, Usage)]
    assert usages[0] == Usage(
        input_tokens=1_840, output_tokens=1, model="claude-haiku-4-5-20251001"
    )
    assert usages[-1] == Usage(
        input_tokens=1_840, output_tokens=612, model="claude-haiku-4-5-20251001"
    )


async def test_anthropic_refusing_the_key_fails_the_credential() -> None:
    recorder = _Recorder(401, b'{"error": "invalid x-api-key"}')

    with pytest.raises(CredentialFailedError):
        await _events(AnthropicProvider(), recorder)


async def test_openai_asks_for_the_usage_and_reads_it_from_the_last_chunk() -> None:
    recorder = _Recorder(
        200,
        _sse(
            {"model": "gpt-5-mini-2025-08-07", "choices": [{"delta": {"content": "Hel"}}]},
            {"model": "gpt-5-mini-2025-08-07", "choices": [{"delta": {"content": "lo"}}]},
            {
                "model": "gpt-5-mini-2025-08-07",
                "choices": [],
                "usage": {"prompt_tokens": 900, "completion_tokens": 40},
            },
        )
        + b"data: [DONE]\n\n",
    )

    events = await _events(OpenAICompatibleProvider(), recorder)

    assert recorder.sent[0]["stream_options"] == {"include_usage": True}
    assert [e.text for e in events if isinstance(e, TextDelta)] == ["Hel", "lo"]
    assert [e for e in events if isinstance(e, Usage)] == [
        Usage(input_tokens=900, output_tokens=40, model="gpt-5-mini-2025-08-07")
    ]


async def test_a_local_model_is_not_asked_for_usage_it_may_not_understand() -> None:
    recorder = _Recorder(200, _sse({"choices": [{"delta": {"content": "Hi"}}]}))

    events = await _events(LocalProvider(), recorder)

    assert "stream_options" not in recorder.sent[0]
    assert events == [TextDelta("Hi")]


async def test_google_yields_its_whole_reply_with_the_usage_it_reported() -> None:
    recorder = _Recorder(
        200,
        json.dumps(
            {
                "candidates": [{"content": {"parts": [{"text": "Hello"}]}}],
                "usageMetadata": {"promptTokenCount": 300, "candidatesTokenCount": 20},
            }
        ).encode(),
    )

    events = await _events(GoogleProvider(), recorder)

    assert events == [
        TextDelta("Hello"),
        Usage(input_tokens=300, output_tokens=20, model="claude-haiku-4-5"),
    ]
