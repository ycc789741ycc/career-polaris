"""Provider adapters.

Every adapter speaks raw HTTP through ``kernel.fetch.GuardedClient`` rather
than a vendor SDK. That is deliberate: the user picks the provider *and* may
supply their own base URL, so every request has to pass the same SSRF guard and
be re-validated on each redirect. Routing one provider through its SDK and the
rest through HTTP would leave that guard with a hole in it.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Protocol

from kernel.fetch import GuardedClient


@dataclass(frozen=True, slots=True)
class Completion:
    text: str
    input_tokens: int
    output_tokens: int
    model: str
    # True when the counts are ours, not the provider's: a stream that
    # reported none, or one cut short.
    is_estimated: bool = False


@dataclass(frozen=True, slots=True)
class Request:
    api_key: str
    model: str
    base_url: str
    system: str
    user: str
    max_output_tokens: int


@dataclass(frozen=True, slots=True)
class TextDelta:
    """A piece of the reply, as it arrives."""

    text: str


@dataclass(frozen=True, slots=True)
class Usage:
    """What the provider says the call used, so far.

    A stream may report it more than once (Anthropic sends the input tokens
    first and the output at the end); the last one is the call's. A provider
    that reports nothing leaves the gateway to estimate, and the ledger says
    so.
    """

    input_tokens: int
    output_tokens: int
    model: str


type StreamEvent = TextDelta | Usage


class Provider(Protocol):
    name: str
    default_base_url: str

    async def complete(self, client: GuardedClient, request: Request) -> Completion: ...

    def stream(self, client: GuardedClient, request: Request) -> AsyncGenerator[StreamEvent]: ...
