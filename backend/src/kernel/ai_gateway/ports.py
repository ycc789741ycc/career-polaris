"""What the gateway needs from the rest of the system, as protocols.

The kernel knows no domain (import-linter contract ``kernel-knows-no-domain``),
so ``identity`` supplies these at the composition root instead of the gateway
importing it. That also makes the gateway testable against a stub with no
database.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Protocol


class Funding(StrEnum):
    """Whose key pays for a call (ADR 0064)."""

    OWN = "own"
    PLATFORM = "platform"


@dataclass(frozen=True, slots=True)
class ProviderCredential:
    """A user's AI credential, still encrypted.

    The gateway is the only place the key is opened, and only for the duration
    of one call.
    """

    provider: str
    model: str
    base_url: str | None
    encrypted_api_key: str
    owner_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class PlatformCredential:
    """This user's calls run on the platform's key, which only the gateway
    holds: the provider, the model and the key come from its settings."""

    owner_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class UsageRecord:
    """One row of the AIUsageLedger.

    The counts are the provider's, unless ``is_estimated``. The estimate the
    call was priced at before it was made is kept beside them, so the two can
    be compared.
    """

    owner_id: uuid.UUID
    task: str
    provider: str
    model: str
    template_version: str
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal
    estimated_input_tokens: int
    estimated_cost_usd: Decimal
    is_estimated: bool
    funding: Funding
    # False when ``pricing.json`` has no rate for the model, so ``cost_usd``
    # is the deliberately high fallback, not what the provider billed.
    is_rate_published: bool = True


class CredentialStore(Protocol):
    async def load(self, owner_id: uuid.UUID) -> ProviderCredential | PlatformCredential:
        """The key this user's calls run on: their own, or the platform's."""
        ...

    async def mark_failed(self, owner_id: uuid.UUID, reason: str) -> None:
        """Emit ProviderCredentialFailed and pause this user's background jobs.

        Only ever for the user's own key: the platform's failing is not theirs.
        """
        ...


class PlatformSpend(Protocol):
    """The meter on the platform's key (ADR 0064): a call reserves the most
    it can cost before it is sent, settles what each attempt really cost, and
    releases the rest when it ends."""

    async def create_reservation(self, owner_id: uuid.UUID, ceiling_usd: Decimal) -> object:
        """Raise when the account's month, or the platform's day or month,
        has no room for ``ceiling_usd``; otherwise a handle to settle with."""
        ...

    async def update_spent(self, reservation: object, cost_usd: Decimal) -> None: ...

    async def delete_reservation(self, reservation: object) -> None: ...


class BudgetGuard(Protocol):
    async def check(
        self,
        owner_id: uuid.UUID,
        estimated_cost_usd: Decimal,
        *,
        funding: Funding,
        is_priced: bool = True,
    ) -> None:
        """Raise ``BudgetExceededError`` when a call on the user's own key
        would breach their cap. A call on a model with no published rate is
        not held to it: its cost would only be our guess."""
        ...

    async def record(self, usage: UsageRecord) -> None: ...
