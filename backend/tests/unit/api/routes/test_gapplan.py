"""Gap plans at the HTTP edge: queued with a status, refused in the envelope.

Runs the real routers and error handlers in-process against stand-in services —
no network, no infra, no queue.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from advisor.gapplan import PlanStatus, PlanSummaryView
from advisor.target import TargetRef
from api import errors
from api.dependencies import current_user, get_container
from api.routes import gapplan as gapplan_api
from kernel.errors import TargetUnusableError

PLAN_ID = uuid.uuid4()


def summary(ref: TargetRef, status: PlanStatus = PlanStatus.DRAFTING) -> PlanSummaryView:
    return PlanSummaryView(
        id=PLAN_ID,
        target=ref,
        label="Staff Platform Engineer · Meridian Labs",
        version=1,
        status=status,
        error_code=None,
        error_message=None,
        model_id=None,
        created_at=datetime(2026, 9, 23, tzinfo=UTC),
        drafted_at=None,
        progress=0,
    )


class FakeGapPlans:
    def __init__(self) -> None:
        self.refuse = False
        self.done: list[tuple[uuid.UUID, bool]] = []
        self.priced: list[TargetRef] = []

    async def request(self, owner_id: uuid.UUID, ref: TargetRef) -> PlanSummaryView:
        if self.refuse:
            raise TargetUnusableError("nothing is known yet; paste its job description instead")
        return summary(ref)

    async def history(self, owner_id: uuid.UUID) -> list[PlanSummaryView]:
        return [summary(TargetRef(str(uuid.uuid4())), PlanStatus.READY)]

    async def estimate_cost(self, owner_id: uuid.UUID, ref: TargetRef) -> dict[str, Any]:
        self.priced.append(ref)
        return {
            "cost_usd": "0.04",
            "model_id": "claude-opus-5",
            "input_tokens": 1200,
            "rate_is_published": True,
        }

    async def set_task_done(self, owner_id: uuid.UUID, task_id: uuid.UUID, done: bool) -> None:
        self.done.append((task_id, done))


@pytest.fixture
def plans() -> FakeGapPlans:
    return FakeGapPlans()


@pytest.fixture
def queued(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def enqueue(name: str, **kwargs: Any) -> None:
        calls.append({"name": name, **kwargs})

    monkeypatch.setattr(gapplan_api, "enqueue", enqueue)
    return calls


@pytest.fixture
def client(plans: FakeGapPlans, queued: list[dict[str, Any]]) -> TestClient:
    app = FastAPI()
    errors.install(app)
    app.include_router(gapplan_api.router)
    user = uuid.uuid4()
    app.dependency_overrides[current_user] = lambda: user
    app.dependency_overrides[get_container] = lambda: SimpleNamespace(gapplan=plans)
    return TestClient(app, raise_server_exceptions=False)


def test_requesting_a_plan_queues_it_and_returns_its_status(
    client: TestClient, queued: list[dict[str, Any]]
) -> None:
    role, opening = str(uuid.uuid4()), str(uuid.uuid4())
    response = client.post("/gap-plans", json={"role_id": role, "job_posting_id": opening})

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "drafting"
    assert body["target"] == {"role_id": role, "job_posting_id": opening}
    assert [(job["name"], job["plan_id"]) for job in queued] == [("gapplan.draft", str(PLAN_ID))]


def test_a_target_that_cannot_be_planned_for_is_refused_before_anything_is_queued(
    client: TestClient, plans: FakeGapPlans, queued: list[dict[str, Any]]
) -> None:
    plans.refuse = True
    response = client.post("/gap-plans", json={"role_id": str(uuid.uuid4())})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "target_unusable"
    assert queued == []


def test_a_target_without_a_role_is_refused_in_the_envelope(client: TestClient) -> None:
    response = client.get(f"/gap-plans/cost-estimate?job_posting_id={uuid.uuid4()}")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"


def test_the_estimate_is_for_the_target_asked_about(
    client: TestClient, plans: FakeGapPlans
) -> None:
    role = uuid.uuid4()
    response = client.get(f"/gap-plans/cost-estimate?role_id={role}")
    assert response.status_code == 200
    assert plans.priced == [TargetRef(str(role))]
    assert response.json() == {
        "cost_usd": "0.04",
        "model_id": "claude-opus-5",
        "input_tokens": 1200,
        "rate_is_published": True,
    }


def test_ticking_a_task_is_recorded(client: TestClient, plans: FakeGapPlans) -> None:
    task = uuid.uuid4()
    response = client.put(f"/gap-plan-tasks/{task}", json={"done": True})
    assert response.status_code == 204
    assert plans.done == [(task, True)]


def test_the_old_kind_and_id_shape_is_refused(client: TestClient) -> None:
    response = client.post("/gap-plans", json={"kind": "matchedPosting", "id": str(uuid.uuid4())})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"
