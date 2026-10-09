"""Reporting to Atlassian the accounts we hold personal data about (ADR 0061).

Atlassian's terms ask every app that stores personal data from its products
to name each account by its ``accountId`` once a cycle, and to erase what it
holds when the reply says the account was closed. The reply is read here into
what the profile should do next; sending it is the infrastructure's job.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from advisor.profile.domain.constants import REPORT_CYCLE_SECONDS, REPORT_RETRY_SECONDS


class ReportedStatus(StrEnum):
    """What Atlassian says changed about an account since we fetched its data."""

    CLOSED = "closed"
    UPDATED = "updated"


class ReportAction(StrEnum):
    NONE = "none"
    # The account was closed: everything from it is erased.
    DISCONNECT = "disconnect"
    # Our copy is out of date: fetching it again replaces it.
    SYNC = "sync"


@dataclass(frozen=True, slots=True)
class ReportedAccount:
    """One account as a report names it: who, and when we last fetched their data."""

    account_id: str
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class AccountReportReply:
    """Atlassian's answer to one report.

    ``statuses`` holds only the accounts that need something done; an account
    it leaves out is fine as it is. ``retry_after_seconds`` is set when the
    report was refused for being sent too often, and nothing else is then.
    """

    statuses: dict[str, ReportedStatus] = field(default_factory=dict)
    cycle_period_seconds: int | None = None
    retry_after_seconds: int | None = None


@dataclass(frozen=True, slots=True)
class ReportDecision:
    """What one report leads to. ``next_report_in_seconds`` is None when the
    connection is gone, which ends that account's reports."""

    action: ReportAction
    next_report_in_seconds: int | None


def parse_cycle_period(header: str | None) -> int | None:
    """A Cycle-Period header as whole seconds, or None when absent or unreadable.

    Atlassian does not document the header's format; a positive number of
    seconds is the only reading taken, and anything else falls back to the
    default cycle.
    """
    if header is None:
        return None
    try:
        seconds = int(header.strip())
    except ValueError:
        return None
    return seconds if seconds > 0 else None


def parse_reported_status(value: object) -> ReportedStatus | None:
    try:
        return ReportedStatus(str(value))
    except ValueError:
        return None


def get_report_decision(
    reply: AccountReportReply, account_id: str, *, jitter_seconds: int
) -> ReportDecision:
    """What to do about one account after a report, and when to report it next."""
    if reply.retry_after_seconds is not None:
        return ReportDecision(ReportAction.NONE, reply.retry_after_seconds + jitter_seconds)

    status = reply.statuses.get(account_id)
    if status is ReportedStatus.CLOSED:
        return ReportDecision(ReportAction.DISCONNECT, None)

    cycle = reply.cycle_period_seconds or REPORT_CYCLE_SECONDS
    action = ReportAction.SYNC if status is ReportedStatus.UPDATED else ReportAction.NONE
    return ReportDecision(action, cycle + jitter_seconds)


def get_report_retry(*, jitter_seconds: int) -> ReportDecision:
    """A report that could not be sent this time: try again, change nothing."""
    return ReportDecision(ReportAction.NONE, REPORT_RETRY_SECONDS + jitter_seconds)


def get_report_end() -> ReportDecision:
    """The connection is gone, so there is nothing left to report."""
    return ReportDecision(ReportAction.NONE, None)
