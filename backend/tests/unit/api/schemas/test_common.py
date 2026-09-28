"""The shared wire shapes keep the forms the client has always read."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from advisor.market import SalaryRange
from api.schemas.common import Accepted, ApiModel, JobError, Salary, Timestamp


class Stamped(ApiModel):
    at: Timestamp


def test_a_timestamp_keeps_its_offset_rather_than_becoming_z() -> None:
    body = Stamped(at=datetime(2026, 9, 27, 9, 0, tzinfo=UTC)).model_dump(mode="json")
    assert body == {"at": "2026-09-27T09:00:00+00:00"}


def test_a_job_without_an_error_code_has_no_error() -> None:
    assert JobError.of(None, "ignored") is None
    assert JobError.of("ai_budget_exceeded", "spent") == JobError(
        code="ai_budget_exceeded", message="spent"
    )


def test_a_salary_is_sent_as_min_max_and_currency() -> None:
    salary = Salary.of(SalaryRange(min_amount=150_000, max_amount=190_000, currency="USD"))
    assert salary is not None
    assert salary.model_dump() == {"min": 150_000, "max": 190_000, "currency": "USD"}
    assert Salary.of(None) is None


def test_a_response_refuses_a_field_its_schema_does_not_name() -> None:
    """Building a body with a stray field is a bug in the route, not data to send."""
    with pytest.raises(ValidationError):
        Accepted.model_validate({"status": "queued", "extra": "x"})


def test_an_accepted_job_says_it_is_queued() -> None:
    assert Accepted().model_dump() == {"status": "queued"}
