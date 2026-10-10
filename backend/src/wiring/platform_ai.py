"""The meter on the platform's AI key (ADR 0064): what each account may spend
on it in a month, and what every account together may spend in a UTC day and
in a month, named once from the settings."""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

from kernel.ai_gateway import PlatformSpend
from kernel.config import Settings
from kernel.errors import PlatformAiQuotaReachedError, PlatformAiUnavailableError
from kernel.limits import (
    Charge,
    Reservation,
    SpendLimit,
    SpendMeter,
    SpendState,
    SpendWindow,
)

# Every account together is one subject.
_EVERYONE = "everyone"
# Beyond the longest a call can take, so a reservation outlives the call it
# guards; one whose process died lapses this long after it was made.
_HOLD_MARGIN = timedelta(minutes=10)


class PlatformSpendMeter(PlatformSpend):
    def __init__(self, meter: SpendMeter, settings: Settings) -> None:
        self._meter = meter
        attempts = settings.ai_max_output_retries + 1
        self._hold = timedelta(seconds=settings.ai_request_timeout_seconds * attempts) + (
            _HOLD_MARGIN
        )
        self._account = SpendLimit(
            name="platform-ai:account",
            allowed_usd=_usd(settings.platform_ai_monthly_quota_usd),
            window=SpendWindow.MONTH,
            refusal=PlatformAiQuotaReachedError,
            message=(
                "You have used this month's CareerPolaris AI. Use your own key to keep "
                "going, or wait for next month."
            ),
        )
        self._day = SpendLimit(
            name="platform-ai:day",
            allowed_usd=_usd(settings.platform_ai_daily_ceiling_usd),
            window=SpendWindow.DAY,
            refusal=PlatformAiUnavailableError,
            message=(
                "CareerPolaris's AI is used up for today. Use your own key to keep going, "
                "or try again tomorrow."
            ),
        )
        self._month = SpendLimit(
            name="platform-ai:month",
            allowed_usd=_usd(settings.platform_ai_monthly_ceiling_usd),
            window=SpendWindow.MONTH,
            refusal=PlatformAiUnavailableError,
            message=(
                "CareerPolaris's AI is used up for this month. Use your own key to keep going."
            ),
        )

    def _charges(self, owner_id: uuid.UUID) -> list[Charge]:
        # The account's own quota first: it is the refusal the user can act on.
        return [
            Charge(self._account, str(owner_id)),
            Charge(self._day, _EVERYONE),
            Charge(self._month, _EVERYONE),
        ]

    async def create_reservation(self, owner_id: uuid.UUID, ceiling_usd: Decimal) -> object:
        return await self._meter.create_reservation(
            self._charges(owner_id), ceiling_usd, hold=self._hold
        )

    async def update_spent(self, reservation: object, cost_usd: Decimal) -> None:
        await self._meter.update_spent(_reservation(reservation), cost_usd)

    async def delete_reservation(self, reservation: object) -> None:
        await self._meter.delete_reservation(_reservation(reservation))

    async def get_account_state(self, owner_id: uuid.UUID) -> SpendState:
        """This account's month on the platform's key."""
        return await self._meter.get_state(Charge(self._account, str(owner_id)))

    async def get_platform_states(self) -> tuple[SpendState, SpendState]:
        """Every account's day and month together."""
        return (
            await self._meter.get_state(Charge(self._day, _EVERYONE)),
            await self._meter.get_state(Charge(self._month, _EVERYONE)),
        )


def _usd(value: float) -> Decimal:
    return Decimal(str(value))


def _reservation(handle: object) -> Reservation:
    if not isinstance(handle, Reservation):
        raise TypeError(f"not a spend reservation: {type(handle).__name__}")
    return handle
