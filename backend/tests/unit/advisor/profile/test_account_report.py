"""Reading Atlassian's reply to a personal data report into what happens next (ADR 0061)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from advisor.profile.domain import (
    AccountReportReply,
    ReportAction,
    ReportedAccount,
    ReportedStatus,
    get_report_decision,
    parse_cycle_period,
)
from advisor.profile.domain.constants import REPORT_CYCLE_SECONDS
from advisor.profile.infra.account_report import AtlassianAccountReporter
from kernel.errors import UpstreamFailedError

ACCOUNT = "5be24ad8b1653240376955d2"


# --- the decision ---------------------------------------------------------------


def test_an_account_needing_nothing_is_reported_again_a_cycle_later() -> None:
    decision = get_report_decision(AccountReportReply(), ACCOUNT, jitter_seconds=30)
    assert decision.action is ReportAction.NONE
    assert decision.next_report_in_seconds == REPORT_CYCLE_SECONDS + 30


def test_a_closed_account_is_disconnected_and_never_reported_again() -> None:
    reply = AccountReportReply(statuses={ACCOUNT: ReportedStatus.CLOSED})
    decision = get_report_decision(reply, ACCOUNT, jitter_seconds=30)
    assert decision.action is ReportAction.DISCONNECT
    assert decision.next_report_in_seconds is None


def test_an_updated_account_is_synced_again_and_stays_reported() -> None:
    reply = AccountReportReply(statuses={ACCOUNT: ReportedStatus.UPDATED})
    decision = get_report_decision(reply, ACCOUNT, jitter_seconds=0)
    assert decision.action is ReportAction.SYNC
    assert decision.next_report_in_seconds == REPORT_CYCLE_SECONDS


def test_another_accounts_status_changes_nothing_for_this_one() -> None:
    reply = AccountReportReply(statuses={"someone-else": ReportedStatus.CLOSED})
    assert get_report_decision(reply, ACCOUNT, jitter_seconds=0).action is ReportAction.NONE


def test_a_cycle_atlassian_names_replaces_the_default() -> None:
    reply = AccountReportReply(cycle_period_seconds=3 * 24 * 3600)
    decision = get_report_decision(reply, ACCOUNT, jitter_seconds=0)
    assert decision.next_report_in_seconds == 3 * 24 * 3600


def test_a_report_sent_too_often_waits_as_long_as_it_was_told() -> None:
    decision = get_report_decision(
        AccountReportReply(retry_after_seconds=120), ACCOUNT, jitter_seconds=5
    )
    assert decision.action is ReportAction.NONE
    assert decision.next_report_in_seconds == 125


@pytest.mark.parametrize(
    ("header", "seconds"),
    [(None, None), ("604800", 604800), (" 86400 ", 86400), ("0", None), ("P7D", None)],
)
def test_a_cycle_period_is_read_as_seconds_or_not_at_all(
    header: str | None, seconds: int | None
) -> None:
    assert parse_cycle_period(header) == seconds


# --- sending it -----------------------------------------------------------------


class FakeAtlassian:
    def __init__(self, response: httpx.Response) -> None:
        self.response = response
        self.sent: list[dict[str, Any]] = []

    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        self.sent.append({"method": method, "url": url, **kwargs})
        return self.response


FETCHED = datetime(2026, 10, 9, 3, 12, 44, 123456, tzinfo=UTC)


async def _send(response: httpx.Response) -> tuple[AccountReportReply, FakeAtlassian]:
    atlassian = FakeAtlassian(response)
    reply = await AtlassianAccountReporter("https://api.atlassian.test/").report(
        atlassian,  # type: ignore[arg-type]
        "owner-token",
        [ReportedAccount(ACCOUNT, FETCHED)],
    )
    return reply, atlassian


async def test_the_report_names_the_account_and_when_its_data_was_fetched() -> None:
    _reply, atlassian = await _send(httpx.Response(204))

    (sent,) = atlassian.sent
    assert sent["method"] == "POST"
    assert sent["url"] == "https://api.atlassian.test/app/report-accounts/"
    assert sent["headers"]["Authorization"] == "Bearer owner-token"
    assert sent["json"] == {
        "accounts": [{"accountId": ACCOUNT, "updatedAt": "2026-10-09T03:12:44.123Z"}]
    }


async def test_no_content_means_nothing_to_do() -> None:
    reply, _ = await _send(httpx.Response(204, headers={"Cycle-Period": "86400"}))
    assert reply.statuses == {}
    assert reply.cycle_period_seconds == 86400


async def test_a_reply_lists_the_accounts_that_need_something_done() -> None:
    reply, _ = await _send(
        httpx.Response(
            200,
            json={
                "accounts": [
                    {"accountId": ACCOUNT, "status": "closed"},
                    {"accountId": "b", "status": "updated"},
                    {"accountId": "c", "status": "something-new"},
                ]
            },
        )
    )
    assert reply.statuses == {ACCOUNT: ReportedStatus.CLOSED, "b": ReportedStatus.UPDATED}


async def test_rate_limited_takes_retry_after() -> None:
    reply, _ = await _send(httpx.Response(429, headers={"Retry-After": "90"}))
    assert reply.retry_after_seconds == 90


async def test_a_malformed_report_is_an_upstream_failure() -> None:
    with pytest.raises(UpstreamFailedError, match="malformed"):
        await _send(httpx.Response(400, json={"errorType": "x", "errorMessage": "y"}))


@pytest.mark.parametrize("status", [401, 500, 503])
async def test_any_other_failure_is_an_upstream_failure(status: int) -> None:
    with pytest.raises(UpstreamFailedError, match=str(status)):
        await _send(httpx.Response(status))
