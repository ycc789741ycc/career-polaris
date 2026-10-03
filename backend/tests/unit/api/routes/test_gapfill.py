"""Fill the gap at the HTTP edge: requesting questions and the one submit (ADR
0023), which spends nothing (ADR 0035). Runs the real router in-process against stand-in
services — no network, no infra, no queue."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from advisor.gapfill import Answer, GapView, QuestionSetView, QuestionView, SubmittedView
from advisor.target import TargetRef
from api import errors
from api.dependencies import current_user, get_container
from api.routes import gapfill as gapfill_api

SET_ID = uuid.uuid4()
QUESTION_ID = uuid.uuid4()
ROLE = uuid.uuid4()


def _set(status: str = "ready") -> QuestionSetView:
    return QuestionSetView(
        id=SET_ID,
        target=TargetRef(str(ROLE)),
        label="Staff Backend Engineer · Northwind Pay",
        status=status,
        gaps=(GapView("dim:incidents", "Own incidents end to end", "partial", 9),),
        questions=(
            QuestionView(
                id=QUESTION_ID,
                gap_key="dim:incidents",
                text="On call?",
                asked_because="One review.",
                answer_type="choice",
                choices=("Yes", "No"),
                evidence_id=None,
            ),
        ),
        model_id="claude-opus-5",
        error_code=None,
        error_message=None,
        created_at=datetime(2026, 9, 29, tzinfo=UTC),
        submitted_at=None,
    )


class FakeGapFill:
    def __init__(self) -> None:
        self.submitted: list[list[Answer]] = []
        self.has_set = True

    async def current(self, owner_id: uuid.UUID, ref: TargetRef) -> QuestionSetView | None:
        return _set() if self.has_set else None

    async def request(self, owner_id: uuid.UUID, ref: TargetRef) -> QuestionSetView:
        return _set("writing")

    async def get(self, owner_id: uuid.UUID, set_id: uuid.UUID) -> QuestionSetView:
        return _set()

    async def submit(
        self, owner_id: uuid.UUID, set_id: uuid.UUID, answers: list[Answer]
    ) -> SubmittedView:
        self.submitted.append(list(answers))
        return SubmittedView(set_id=set_id, evidence_ids=(uuid.uuid4(),), skipped=0)


@pytest.fixture
def gapfill() -> FakeGapFill:
    return FakeGapFill()


@pytest.fixture
def queued(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def enqueue(name: str, **kwargs: Any) -> None:
        calls.append({"name": name, **kwargs})

    monkeypatch.setattr(gapfill_api, "enqueue", enqueue)
    return calls


def _client(gapfill: FakeGapFill) -> TestClient:
    app = FastAPI()
    errors.install(app)
    app.include_router(gapfill_api.router)
    app.dependency_overrides[current_user] = lambda: uuid.uuid4()
    app.dependency_overrides[get_container] = lambda: SimpleNamespace(gapfill=gapfill)
    return TestClient(app, raise_server_exceptions=False)


def test_requesting_questions_queues_them_and_returns_the_set(
    gapfill: FakeGapFill, queued: list[dict[str, Any]]
) -> None:
    response = _client(gapfill).post("/gap-question-sets", json={"role_id": str(ROLE)})

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "writing"
    assert body["target"] == {
        "role_id": str(ROLE),
        "job_posting_id": None,
        "private_job_posting_id": None,
    }
    [gap] = body["gaps"]
    assert (gap["key"], gap["status"], gap["lift"]) == ("dim:incidents", "partial", 9)
    assert [(c["name"], c["set_id"]) for c in queued] == [("gapfill.write", str(SET_ID))]


def test_there_is_no_current_set_before_any_was_written(gapfill: FakeGapFill) -> None:
    gapfill.has_set = False
    response = _client(gapfill).get(f"/gap-question-sets/current?role_id={ROLE}")

    assert response.status_code == 200 and response.json() is None


def test_submitting_has_no_price_to_ask_for(gapfill: FakeGapFill) -> None:
    """Answering spends nothing, so there is nothing to estimate (ADR 0035)."""
    response = _client(gapfill).get(f"/gap-question-sets/{SET_ID}/submit-estimate")

    assert response.status_code in (404, 405)


def test_every_answer_arrives_in_one_submit_and_queues_nothing(
    gapfill: FakeGapFill, queued: list[dict[str, Any]]
) -> None:
    response = _client(gapfill).post(
        f"/gap-question-sets/{SET_ID}/answers",
        json={"answers": [{"question_id": str(QUESTION_ID), "choice": "Yes"}]},
    )

    assert response.status_code == 200
    assert response.json()["answered"] == 1
    assert gapfill.submitted == [[Answer(question_id=QUESTION_ID, choice="Yes", text=None)]]
    assert queued == []


def test_an_empty_submit_is_refused_in_the_envelope(gapfill: FakeGapFill) -> None:
    response = _client(gapfill).post(f"/gap-question-sets/{SET_ID}/answers", json={"answers": []})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"
    assert gapfill.submitted == []
