"""The limits the api applies per account (ADR 0054), named
once from the settings. Routes record an attempt against one before the work."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from kernel.config import Settings
from kernel.limits import Limit


@dataclass(frozen=True, slots=True)
class Limits:
    uploads: Limit
    syncs: Limit


def create_limits(settings: Settings) -> Limits:
    return Limits(
        uploads=Limit(
            name="uploads",
            allowed=settings.uploads_per_account_per_day,
            window=timedelta(days=1),
            refusal="You have uploaded as many files as one day allows.",
        ),
        syncs=Limit(
            name="syncs",
            allowed=settings.syncs_per_account_per_hour,
            window=timedelta(hours=1),
            refusal="You have synced as often as one hour allows.",
        ),
    )
