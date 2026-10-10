"""The meter on the platform's AI key (ADR 0064): what each account may spend
on it in a month, and what every account together may spend in a UTC day and
in a month, named once from the settings.

It also tells the operator, in the log, when everyone's spend nears a ceiling
(WARN, once per window and process) and when a ceiling refuses a call
(ERROR): the two moments worth acting on.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

from kernel.ai_gateway import PlatformSpend
from kernel.clock import utcnow
from kernel.config import Settings
from kernel.errors import PlatformAiQuotaReachedError, PlatformAiUnavailableError
from kernel.limits import (
    Charge,
    Reservation,
    SpendLimit,
    SpendMeter,
    SpendState,
    SpendWindow,
    get_spend_window_start,
)
from kernel.logging import get_logger

log = get_logger(__name__)

# Every account together is one subject.
_EVERYONE = "everyone"
# The share of a ceiling past which the operator is warned.
NEAR_CEILING = Decimal("0.8")
# Beyond the longest a call can take, so a reservation outlives the call it
# guards; one whose process died lapses this long after it was made.
_HOLD_MARGIN = timedelta(minutes=10)


class PlatformSpendMeter(PlatformSpend):
    def __init__(self, meter: SpendMeter, settings: Settings) -> None:
        self._meter = meter
        # The ceilings' windows already warned about by this process.
        self._warned: set[tuple[str, object]] = set()
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
        try:
            reservation = await self._meter.create_reservation(
                self._charges(owner_id), ceiling_usd, hold=self._hold
            )
        except PlatformAiUnavailableError as refused:
            log.error(
                "platform_ai.ceiling_reached",
                limit=refused.context.get("limit"),
                ceiling_usd=str(ceiling_usd),
            )
            raise
        await self._warn_near_ceiling()
        return reservation

    async def _warn_near_ceiling(self) -> None:
        for limit in (self._day, self._month):
            key = (limit.name, get_spend_window_start(utcnow(), limit.window))
            if key in self._warned:
                continue
            state = await self._meter.get_state(Charge(limit, _EVERYONE))
            used = state.spent_usd + state.reserved_usd
            if used >= limit.allowed_usd * NEAR_CEILING:
                self._warned.add(key)
                log.warning(
                    "platform_ai.near_ceiling",
                    limit=limit.name,
                    used_usd=str(used),
                    allowed_usd=str(limit.allowed_usd),
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
