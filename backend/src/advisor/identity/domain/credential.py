"""Rules for the one AI credential in the system.

Write-only: it can be set, tested, replaced or deleted, but never read back.
What the client may see is the provider, the model and the last four
characters (docs/architecture.md section 4).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class CredentialStatus(StrEnum):
    ACTIVE = "active"
    FAILED = "failed"


class Provider(StrEnum):
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    GOOGLE = "google"


# Shown in the settings screen. A user may type any model their provider
# serves; these are ids each provider's API takes, and every one has a
# published rate in pricing.json (a unit test holds that).
SUGGESTED_MODELS: dict[Provider, tuple[str, ...]] = {
    Provider.ANTHROPIC: (
        "claude-opus-5",
        "claude-sonnet-5",
        "claude-haiku-4-5",
    ),
    Provider.OPENAI: ("gpt-5.1", "gpt-5-mini"),
    Provider.GOOGLE: ("gemini-3-pro-preview", "gemini-3-flash-preview"),
}


@dataclass(frozen=True, slots=True)
class CredentialView:
    """Everything the client is ever told about a stored credential."""

    provider: Provider
    model: str
    base_url: str | None
    last_four: str
    status: CredentialStatus
    last_error: str | None


def accepts_base_url(provider: Provider) -> bool:
    """Only an OpenAI key may name its own endpoint: an OpenAI-compatible
    cloud (Azure OpenAI, Groq, Together) at a public URL. A model on the
    user's own machine is out of reach of a hosted service (ADR 0065)."""
    return provider is Provider.OPENAI


@dataclass(slots=True)
class ProviderCredential:
    """The user's AI provider and key. Written, tested, replaced — never read
    back in the clear."""

    id: uuid.UUID
    owner_id: uuid.UUID
    provider: Provider
    model: str
    base_url: str | None
    # Envelope-encrypted, bound to owner_id as additional authenticated data.
    encrypted_api_key: str
    # The only part of the key the client may ever see.
    last_four: str
    status: CredentialStatus
    last_error: str | None = None
    last_verified_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def configured(
        cls,
        owner_id: uuid.UUID,
        *,
        provider: Provider,
        model: str,
        base_url: str | None,
        encrypted_api_key: str,
        last_four: str,
    ) -> ProviderCredential:
        return cls(
            id=uuid.uuid4(),
            owner_id=owner_id,
            provider=provider,
            model=model,
            base_url=base_url,
            encrypted_api_key=encrypted_api_key,
            last_four=last_four,
            status=CredentialStatus.ACTIVE,
        )

    def failed(self, reason: str) -> None:
        self.status = CredentialStatus.FAILED
        self.last_error = reason
