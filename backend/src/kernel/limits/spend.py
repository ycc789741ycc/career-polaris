"""Money spent per subject and window, reserved before it is spent (ADR 0064).

A call's most it can cost is reserved against every limit it counts toward,
in one transaction that locks each window's row, so two calls at once can
never both fit where only one does. What the call really cost is then
settled into the window, and the reservation released. A reservation that is
never released, because its process died, lapses at ``expires_at``.

Windows are calendar ones: a UTC day, or a calendar month. Subjects are kept
only as digests, as in ``limits.counter``.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import text

from kernel.clock import utcnow
from kernel.db import Database
from kernel.errors import DomainError
from kernel.logging import get_logger

log = get_logger(__name__)

# Windows that started this long ago are deleted, whoever they counted: past
# the longest window, with room for a report on last month.
_KEEP = timedelta(days=70)


class SpendWindow(StrEnum):
    DAY = "day"
    MONTH = "month"


def get_spend_window_start(now: datetime, window: SpendWindow) -> datetime:
    """Midnight UTC of ``now``'s day, or of the first of its month."""
    day = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return day if window is SpendWindow.DAY else day.replace(day=1)


@dataclass(frozen=True, slots=True)
class SpendLimit:
    """At most ``allowed_usd`` per ``window``; past it, ``refusal`` is raised
    with ``message``."""

    name: str
    allowed_usd: Decimal
    window: SpendWindow
    refusal: type[DomainError]
    message: str

    def __post_init__(self) -> None:
        if self.allowed_usd <= 0:
            raise ValueError(f"spend limit {self.name} must allow something")


@dataclass(frozen=True, slots=True)
class Charge:
    """One limit a reservation counts toward, for one subject."""

    limit: SpendLimit
    subject: str

    def get_digest(self) -> str:
        return hashlib.sha256(f"{self.limit.name}\x00{self.subject}".encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class Reservation:
    id: uuid.UUID
    # Each charge's digest and the window it was reserved in, in lock order.
    windows: tuple[tuple[str, datetime], ...]


@dataclass(frozen=True, slots=True)
class SpendState:
    allowed_usd: Decimal
    spent_usd: Decimal
    reserved_usd: Decimal

    @property
    def remaining_usd(self) -> Decimal:
        return max(Decimal(0), self.allowed_usd - self.spent_usd - self.reserved_usd)


class SpendMeter:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def create_reservation(
        self, charges: Sequence[Charge], amount_usd: Decimal, *, hold: timedelta
    ) -> Reservation:
        """Reserve ``amount_usd`` against every charge, or none of them.

        Refuses with the first limit, in the order given, that it would take
        past what it allows. Rows are locked in digest order, so two
        reservations never wait on each other in a circle.
        """
        now = utcnow()
        reservation_id = uuid.uuid4()
        planned = [
            (charge, charge.get_digest(), get_spend_window_start(now, charge.limit.window))
            for charge in charges
        ]
        refused: Charge | None = None
        async with self._database.shared() as session:
            states: dict[str, SpendState] = {}
            for charge, digest, start in sorted(planned, key=lambda item: item[1]):
                await session.execute(
                    text(
                        "INSERT INTO limits.spend_window (key_digest, window_start, spent_usd) "
                        "VALUES (:key, :start, 0) ON CONFLICT DO NOTHING"
                    ),
                    {"key": digest, "start": start},
                )
                spent = (
                    await session.execute(
                        text(
                            "SELECT spent_usd FROM limits.spend_window "
                            "WHERE key_digest = :key AND window_start = :start FOR UPDATE"
                        ),
                        {"key": digest, "start": start},
                    )
                ).scalar_one()
                reserved = (
                    await session.execute(
                        text(
                            "SELECT coalesce(sum(amount_usd), 0) FROM limits.spend_reservation "
                            "WHERE key_digest = :key AND window_start = :start "
                            "AND expires_at > :now"
                        ),
                        {"key": digest, "start": start, "now": now},
                    )
                ).scalar_one()
                states[digest] = SpendState(
                    allowed_usd=charge.limit.allowed_usd,
                    spent_usd=Decimal(spent),
                    reserved_usd=Decimal(reserved),
                )
            for charge, digest, _ in planned:
                if amount_usd > states[digest].remaining_usd:
                    refused = charge
                    break
            if refused is None:
                for _, digest, start in planned:
                    await session.execute(
                        text(
                            "INSERT INTO limits.spend_reservation "
                            "(id, key_digest, window_start, amount_usd, expires_at) "
                            "VALUES (:id, :key, :start, :amount, :expires)"
                        ),
                        {
                            "id": reservation_id,
                            "key": digest,
                            "start": start,
                            "amount": amount_usd,
                            "expires": now + hold,
                        },
                    )
            # Lapsed reservations and windows long over, of any key.
            await session.execute(
                text("DELETE FROM limits.spend_reservation WHERE expires_at <= :now"),
                {"now": now},
            )
            await session.execute(
                text("DELETE FROM limits.spend_window WHERE window_start < :old"),
                {"old": now - _KEEP},
            )
        if refused is not None:
            log.info(
                "limits.spend_refused",
                limit=refused.limit.name,
                amount_usd=str(amount_usd),
            )
            raise refused.limit.refusal(refused.limit.message, limit=refused.limit.name)
        return Reservation(
            id=reservation_id,
            windows=tuple((digest, start) for _, digest, start in planned),
        )

    async def update_spent(self, reservation: Reservation, cost_usd: Decimal) -> None:
        """Move ``cost_usd`` from the reservation into what was spent, in the
        windows it was reserved in. Spend past the reservation still counts."""
        async with self._database.shared() as session:
            for digest, start in sorted(reservation.windows):
                await session.execute(
                    text(
                        "UPDATE limits.spend_window SET spent_usd = spent_usd + :cost "
                        "WHERE key_digest = :key AND window_start = :start"
                    ),
                    {"cost": cost_usd, "key": digest, "start": start},
                )
                await session.execute(
                    text(
                        "UPDATE limits.spend_reservation "
                        "SET amount_usd = greatest(amount_usd - :cost, 0) "
                        "WHERE id = :id AND key_digest = :key"
                    ),
                    {"cost": cost_usd, "id": reservation.id, "key": digest},
                )

    async def delete_reservation(self, reservation: Reservation) -> None:
        """Give back what the call did not use."""
        async with self._database.shared() as session:
            await session.execute(
                text("DELETE FROM limits.spend_reservation WHERE id = :id"),
                {"id": reservation.id},
            )

    async def get_state(self, charge: Charge) -> SpendState:
        """What ``charge``'s current window allows, has spent and holds."""
        now = utcnow()
        start = get_spend_window_start(now, charge.limit.window)
        digest = charge.get_digest()
        async with self._database.shared() as session:
            spent = (
                await session.execute(
                    text(
                        "SELECT coalesce(max(spent_usd), 0) FROM limits.spend_window "
                        "WHERE key_digest = :key AND window_start = :start"
                    ),
                    {"key": digest, "start": start},
                )
            ).scalar_one()
            reserved = (
                await session.execute(
                    text(
                        "SELECT coalesce(sum(amount_usd), 0) FROM limits.spend_reservation "
                        "WHERE key_digest = :key AND window_start = :start AND expires_at > :now"
                    ),
                    {"key": digest, "start": start, "now": now},
                )
            ).scalar_one()
        return SpendState(
            allowed_usd=charge.limit.allowed_usd,
            spent_usd=Decimal(spent),
            reserved_usd=Decimal(reserved),
        )
