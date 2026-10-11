"""Cancelling an analysis run (ADR 0072)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from advisor.assessment.domain import AnalysisRun, AnalysisRunStatus

AT = datetime(2026, 10, 11, 9, 0, tzinfo=UTC)


def test_a_running_run_is_cancelled_and_closed() -> None:
    run = AnalysisRun.requested(owner_id=uuid.uuid4(), at=AT)

    run.cancel(AT)

    assert (run.status, run.finished_at, run.error_code) == (
        AnalysisRunStatus.CANCELLED,
        AT,
        None,
    )
    assert not run.is_running


@pytest.mark.parametrize("close", ["ready", "failed", "cancel"])
def test_a_closed_run_cannot_be_cancelled(close: str) -> None:
    run = AnalysisRun.requested(owner_id=uuid.uuid4(), at=AT)
    if close == "ready":
        run.ready(AT)
    elif close == "failed":
        run.failed(code="internal", message="x", at=AT)
    else:
        run.cancel(AT)

    with pytest.raises(ValueError):
        run.cancel(AT)
