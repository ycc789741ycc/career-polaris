"""The role map's k at the HTTP edge: bounded, and refused in the one envelope;
and a rebuild queued once, or left waiting for an analysis (ADR 0018).

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
from advisor.rolemap.domain import DEFAULT_ROLE_COUNT, MAX_ROLE_COUNT, MIN_ROLE_COUNT
from api import errors
from api.dependencies import current_user, get_container
from api.routes import rolemap as rolemap_api


class FakeRoleMap:
    def __init__(self) -> None:
        self.stored = DEFAULT_ROLE_COUNT
        self.estimated_for: list[int | None] = []

    async def role_count(self, owner_id: uuid.UUID) -> int:
        return self.stored

    async def set_role_count(self, owner_id: uuid.UUID, role_count: int) -> int:
        self.stored = role_count
        return role_count

    async def estimate_cost(
        self, owner_id: uuid.UUID, *, role_count: int | None = None
    ) -> dict[str, Any]:
        self.estimated_for.append(role_count)
        k = role_count or self.stored
        return {"max_clusters": k, "role_count": k, "cost_usd": "0", "model_id": None}


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


def test_an_unset_k_reads_as_the_default(client: TestClient) -> None:
    assert client.get("/roles/settings").json() == {"role_count": DEFAULT_ROLE_COUNT}


def test_a_k_inside_the_bound_is_saved(client: TestClient, rolemap: FakeRoleMap) -> None:
    response = client.put("/roles/settings", json={"role_count": MAX_ROLE_COUNT})
    assert response.status_code == 200
    assert rolemap.stored == MAX_ROLE_COUNT


@pytest.mark.parametrize("role_count", [MIN_ROLE_COUNT - 1, MAX_ROLE_COUNT + 1])
def test_a_k_outside_the_bound_is_refused_in_the_envelope(
    client: TestClient, rolemap: FakeRoleMap, role_count: int
) -> None:
    response = client.put("/roles/settings", json={"role_count": role_count})
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_failed"
    assert error["message"].startswith("role_count:")
    assert rolemap.stored == DEFAULT_ROLE_COUNT


def test_the_estimate_can_price_a_k_before_it_is_saved(
    client: TestClient, rolemap: FakeRoleMap
) -> None:
    response = client.get("/roles/cost-estimate", params={"role_count": 15})
    assert response.status_code == 200
    assert rolemap.estimated_for == [15]
    assert rolemap.stored == DEFAULT_ROLE_COUNT


def test_the_estimate_refuses_a_proposed_k_outside_the_bound(client: TestClient) -> None:
    response = client.get("/roles/cost-estimate", params={"role_count": MAX_ROLE_COUNT + 1})
    assert response.status_code == 422


def test_a_new_k_rebuilds_the_role_map_once(
    client: TestClient, activity: FakeActivity, queued: list[dict[str, Any]]
) -> None:
    client.put("/roles/settings", json={"role_count": MAX_ROLE_COUNT})
    client.put("/roles/settings", json={"role_count": MAX_ROLE_COUNT})

    assert activity.requests == 1
    assert [c["name"] for c in queued] == ["rolemap.recluster"]


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
