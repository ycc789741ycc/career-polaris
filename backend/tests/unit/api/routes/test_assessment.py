"""Follow-up question status at the HTTP edge: what the Clarify page polls.

Runs the real router in-process against a stand-in service — no network, no
infra, no queue.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from advisor.assessment import QuestionRoundView
from api import errors
from api.dependencies import current_user, get_container
from api.routes import assessment as assessment_api

ROUND_ID = uuid.uuid4()


class FakeAssessment:
    def __init__(self) -> None:
        self.round: QuestionRoundView | None = None

    async def latest_round(self, owner_id: uuid.UUID) -> QuestionRoundView | None:
        return self.round


@pytest.fixture
def service() -> FakeAssessment:
    return FakeAssessment()


@pytest.fixture
def client(service: FakeAssessment) -> TestClient:
    app = FastAPI()
    errors.install(app)
    app.include_router(assessment_api.router)
    user = uuid.uuid4()
    app.dependency_overrides[current_user] = lambda: user
    app.dependency_overrides[get_container] = lambda: SimpleNamespace(assessment=service)
    return TestClient(app, raise_server_exceptions=False)


def _round(status: str, *, error_code: str | None = None) -> QuestionRoundView:
    return QuestionRoundView(
        id=ROUND_ID,
        trigger="evidence",
        status=status,
        question_count=0,
        created_at=datetime(2026, 9, 27, 9, 0, tzinfo=UTC),
        finished_at=None if status == "generating" else datetime(2026, 9, 27, 9, 1, tzinfo=UTC),
        error_code=error_code,
        error_message="this month's budget is spent" if error_code else None,
    )


def test_there_is_no_status_before_the_first_round(client: TestClient) -> None:
    response = client.get("/questions/status")

    assert response.status_code == 200 and response.json() is None


def test_a_generating_round_has_no_finish_and_no_error(
    client: TestClient, service: FakeAssessment
) -> None:
    service.round = _round("generating")

    body = client.get("/questions/status").json()

    assert body == {
        "id": str(ROUND_ID),
        "status": "generating",
        "trigger": "evidence",
        "question_count": 0,
        "created_at": "2026-09-27T09:00:00+00:00",
        "finished_at": None,
        "error": None,
    }


def test_a_failed_round_says_why_in_the_error_envelope_terms(
    client: TestClient, service: FakeAssessment
) -> None:
    service.round = _round("failed", error_code="ai_budget_exceeded")

    body = client.get("/questions/status").json()

    assert body["status"] == "failed"
    assert body["error"] == {
        "code": "ai_budget_exceeded",
        "message": "this month's budget is spent",
    }
