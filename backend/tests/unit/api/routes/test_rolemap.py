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

from advisor.rolemap import BuildRequestView, BuildRunView, RoleView
from api import errors
from api.dependencies import current_user, get_container
from api.routes import rolemap as rolemap_api


class FakeRoleMap:
    def __init__(self) -> None:
        self.added: list[dict[str, Any]] = []
        self.removed: list[uuid.UUID] = []

    async def estimate_cost(self, owner_id: uuid.UUID) -> dict[str, Any]:
        return {"max_clusters": 10, "cost_usd": "0.40", "model_id": "claude-opus-5"}

    async def estimate_custom_role(self, owner_id: uuid.UUID, **kw: Any) -> dict[str, Any]:
        return {"matches": 3, "cost_usd": "0.08", "model_id": "claude-opus-5"}

    async def add_custom_role(self, owner_id: uuid.UUID, **kw: Any) -> RoleView:
        self.added.append(kw)
        return RoleView(
            id=ROLE_ID,
            name=kw["title"],
            hiring_bar=50,
            bar_basis="estimated",
            bar_confidence=0.0,
            bar_reasoning=None,
            opening_count=0,
            salary_bands={},
            requirements=(),
            is_coherent=True,
            origin="custom",
            company_name=kw["company_name"],
            private_posting_id=kw["private_posting_id"],
        )

    async def remove_custom_role(self, owner_id: uuid.UUID, role_id: uuid.UUID) -> None:
        self.removed.append(role_id)


ROLE_ID = uuid.uuid4()
JD_ID = uuid.uuid4()


class FakeMarket:
    def __init__(self) -> None:
        self.pasted: list[dict[str, Any]] = []

    async def paste_job_description(self, owner_id: uuid.UUID, **kw: Any) -> Any:
        self.pasted.append(kw)
        return SimpleNamespace(id=JD_ID)


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
def market() -> FakeMarket:
    return FakeMarket()


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
def client(
    rolemap: FakeRoleMap, activity: FakeActivity, market: FakeMarket, queued: list[Any]
) -> TestClient:
    app = FastAPI()
    errors.install(app)
    app.include_router(rolemap_api.router)
    user = uuid.uuid4()
    app.dependency_overrides[current_user] = lambda: user
    app.dependency_overrides[get_container] = lambda: SimpleNamespace(
        rolemap=rolemap, activity=activity, market=market
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


# --- custom roles (ADR 0021) ----------------------------------------------------


def test_adding_a_custom_role_prices_it_first(client: TestClient) -> None:
    response = client.post("/roles/custom/cost-estimate", json={"title": "Staff Engineer"})

    assert response.status_code == 200
    assert response.json()["matches"] == 3


def test_a_custom_roles_jd_is_stored_privately_and_the_build_queued(
    client: TestClient,
    rolemap: FakeRoleMap,
    market: FakeMarket,
    queued: list[dict[str, Any]],
) -> None:
    response = client.post(
        "/roles/custom",
        json={
            "title": "Staff Engineer",
            "company_name": "Northwind",
            "job_description": "Own the ledger.",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert (body["origin"], body["company_name"]) == ("custom", "Northwind")
    assert body["private_posting_id"] == str(JD_ID)
    assert [p["description"] for p in market.pasted] == ["Own the ledger."]
    assert rolemap.added[0]["private_posting_id"] == JD_ID
    assert [c["name"] for c in queued] == ["rolemap.recluster"]


def test_a_custom_role_without_a_jd_stores_none(
    client: TestClient, rolemap: FakeRoleMap, market: FakeMarket
) -> None:
    response = client.post("/roles/custom", json={"title": "Staff Engineer"})

    assert response.status_code == 201
    assert market.pasted == [] and rolemap.added[0]["private_posting_id"] is None


def test_a_custom_role_needs_a_title_before_anything_is_stored(
    client: TestClient, market: FakeMarket
) -> None:
    response = client.post("/roles/custom", json={"title": "", "job_description": "JD"})

    assert response.status_code == 422 and market.pasted == []


def test_a_custom_role_is_removed(client: TestClient, rolemap: FakeRoleMap) -> None:
    assert client.delete(f"/roles/custom/{ROLE_ID}").status_code == 204
    assert rolemap.removed == [ROLE_ID]
