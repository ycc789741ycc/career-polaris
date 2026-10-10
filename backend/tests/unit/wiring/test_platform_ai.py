"""What the platform's meter tells the operator (ADR 0064): a warning as
everyone's spend nears a ceiling, once per window, and an error when a
ceiling refuses a call."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import timedelta
from decimal import Decimal

import pytest
from structlog.testing import capture_logs

from kernel.config import get_settings
from kernel.errors import PlatformAiQuotaReachedError, PlatformAiUnavailableError
from kernel.limits import Charge, Reservation, SpendMeter, SpendState
from wiring.platform_ai import PlatformSpendMeter

OWNER = uuid.UUID("33333333-3333-3333-3333-333333333333")


class FakeMeter(SpendMeter):
    """Everyone has spent ``spent`` of every ceiling; reservations may be refused."""

    def __init__(self, spent: Decimal, refuse: Exception | None = None) -> None:
        self.spent = spent
        self.refuse = refuse

    async def create_reservation(
        self, charges: Sequence[Charge], amount_usd: Decimal, *, hold: timedelta
    ) -> Reservation:
        if self.refuse is not None:
            raise self.refuse
        return Reservation(id=uuid.uuid4(), windows=())

    async def get_state(self, charge: Charge) -> SpendState:
        return SpendState(
            allowed_usd=charge.limit.allowed_usd, spent_usd=self.spent, reserved_usd=Decimal(0)
        )


@pytest.fixture
def settings(clean_env: None, monkeypatch: pytest.MonkeyPatch):
    # Day ceiling $5, month ceiling $50, by default.
    get_settings.cache_clear()
    return get_settings()


async def test_nearing_a_ceiling_warns_the_operator_once(settings) -> None:
    spend = PlatformSpendMeter(FakeMeter(spent=Decimal("4.20")), settings)

    with capture_logs() as logs:
        await spend.create_reservation(OWNER, Decimal("0.10"))
        await spend.create_reservation(OWNER, Decimal("0.10"))

    warnings = [e for e in logs if e["event"] == "platform_ai.near_ceiling"]
    assert [w["limit"] for w in warnings] == ["platform-ai:day"]
    assert warnings[0]["log_level"] == "warning"


async def test_far_from_a_ceiling_nothing_is_said(settings) -> None:
    spend = PlatformSpendMeter(FakeMeter(spent=Decimal("1")), settings)

    with capture_logs() as logs:
        await spend.create_reservation(OWNER, Decimal("0.10"))

    assert [e for e in logs if e["event"] == "platform_ai.near_ceiling"] == []


async def test_a_ceiling_refusing_a_call_is_an_error_for_the_operator(settings) -> None:
    refusal = PlatformAiUnavailableError("used up for today", limit="platform-ai:day")
    spend = PlatformSpendMeter(FakeMeter(spent=Decimal(0), refuse=refusal), settings)

    with capture_logs() as logs, pytest.raises(PlatformAiUnavailableError):
        await spend.create_reservation(OWNER, Decimal("0.10"))

    [error] = [e for e in logs if e["event"] == "platform_ai.ceiling_reached"]
    assert error["log_level"] == "error" and error["limit"] == "platform-ai:day"


async def test_one_accounts_quota_running_out_is_not_the_operators_problem(settings) -> None:
    refusal = PlatformAiQuotaReachedError("your month is used", limit="platform-ai:account")
    spend = PlatformSpendMeter(FakeMeter(spent=Decimal(0), refuse=refusal), settings)

    with capture_logs() as logs, pytest.raises(PlatformAiQuotaReachedError):
        await spend.create_reservation(OWNER, Decimal("0.10"))

    assert [e for e in logs if e["event"] == "platform_ai.ceiling_reached"] == []
