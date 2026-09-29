"""The role map at the HTTP edge: its estimate, and a rebuild queued once, or
left waiting for an analysis (ADR 0018).

Runs the real router and error handlers in-process against a stand-in service —
no network, no infra.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from advisor.rolemap import BuildRequestView, BuildRunView
from api import errors
from api.dependencies import current_user, get_container
from api.routes import rolemap as rolemap_api


class FakeRoleMap:
    async def estimate_cost(self, owner_id: uuid.UUID) -> dict[str, Any]:
        return {"max_clusters": 10, "cost_usd": "0.40", "model_id": "claude-opus-5"}


class FakeActivity:
    """Answers every build request the same way, and counts them."""

    def __init__(self) -> None:
        self.status = "running"
        self.should_queue = True
        self.requests = 0

    async def request_role_map(self, owner_id: uuid.UUID) -> BuildRequestView:
        self.requests += 1
        at = datetime(2026, 9, 28, 9, 0, tzinfo=UTC)
        build = BuildRunView(
            id=uuid.UUID(int=self.requests),
            status=self.status,
            requested_at=at,
            started_at=None if self.status == "waiting" else at,
            finished_at=None,
            error_code=None,
            error_message=None,
        )
        return BuildRequestView(build=build, should_queue=self.should_queue)


@pytest.fixture
def rolemap() -> FakeRoleMap:
    return FakeRoleMap()


@pytest.fixture
def activity() -> FakeActivity:
    return FakeActivity()


@pytest.fixture
def queued(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def enqueue(name: str, **kwargs: Any) -> None:
        calls.append({"name": name, **kwargs})

    monkeypatch.setattr(rolemap_api, "enqueue", enqueue)
    return calls


@pytest.fixture
def client(rolemap: FakeRoleMap, activity: FakeActivity, queued: list[Any]) -> TestClient:
    app = FastAPI()
    errors.install(app)
    app.include_router(rolemap_api.router)
    user = uuid.uuid4()
    app.dependency_overrides[current_user] = lambda: user
    app.dependency_overrides[get_container] = lambda: SimpleNamespace(
        rolemap=rolemap, activity=activity
    )
    return TestClient(app, raise_server_exceptions=False)


def test_the_estimate_prices_the_ten_recommended_roles(client: TestClient) -> None:
    response = client.get("/roles/cost-estimate")
    assert response.status_code == 200
    assert response.json() == {
        "cost_usd": "0.40",
        "model_id": "claude-opus-5",
        "max_clusters": 10,
        "rate_is_published": None,
    }


def test_there_is_no_role_count_to_set(client: TestClient) -> None:
    assert client.put("/roles/settings", json={"role_count": 5}).status_code in (404, 405)


def test_a_rebuild_is_queued_with_its_recorded_build(
    client: TestClient, queued: list[dict[str, Any]]
) -> None:
    response = client.post("/roles/recluster")

    assert response.status_code == 202
    assert response.json()["status"] == "running"
    assert queued == [
        {
            "name": "rolemap.recluster",
            "owner_id": queued[0]["owner_id"],
            "build_id": str(uuid.UUID(int=1)),
        }
    ]


def test_a_rebuild_during_an_analysis_waits_and_is_not_queued(
    client: TestClient, activity: FakeActivity, queued: list[dict[str, Any]]
) -> None:
    activity.status, activity.should_queue = "waiting", False

    response = client.post("/roles/recluster")

    assert response.status_code == 202
    assert response.json()["status"] == "waiting"
    assert queued == []
