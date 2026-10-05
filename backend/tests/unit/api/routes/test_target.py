"""Target at the HTTP edge: the postings the user brings themselves, added
without spending anything, priced and queued when set as the target, listed
and removed (Phase 8, ADR 0033, ADR 0034).

Runs the real router and error handlers in-process against a stand-in service —
no network, no infra.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from advisor.target import OwnPostingView
from api import errors
from api.dependencies import current_user, get_container
from api.routes import target as target_api
from tests.unit.api.routes.fake_limits import LIMITS, FakeLimiter

JD_ID = uuid.uuid4()
RUN_ID = uuid.uuid4()


def _own(
    title: str, *, status: str | None, fit: int | None = None, source: str = "filled_in"
) -> OwnPostingView:
    return OwnPostingView(
        private_job_posting_id=JD_ID,
        title=title,
        company_name="Northwind",
        source=source,
        filename=None,
        has_estimated_requirements=False,
        created_at=None,
        status=status,
        error_code=None,
        error_message=None,
        fit=fit,
        is_stale=False,
        scored_at=None,
    )


class FakeTarget:
    def __init__(self) -> None:
        self.added: list[dict[str, Any]] = []
        self.uploaded: list[dict[str, Any]] = []
        self.removed: list[uuid.UUID] = []
        self.target_run: uuid.UUID | None = RUN_ID

    async def add_own_posting(self, owner_id: uuid.UUID, **kw: Any) -> OwnPostingView:
        self.added.append(kw)
        return _own(kw["title"], status=None)

    async def upload_own_posting(self, owner_id: uuid.UUID, **kw: Any) -> OwnPostingView:
        self.uploaded.append(kw)
        return _own(kw["title"] or "jd", status=None, source="uploaded")

    async def estimate_target(self, owner_id: uuid.UUID, posting_id: uuid.UUID) -> dict[str, Any]:
        return {"cost_usd": "0.18", "model_id": "claude-opus-5", "rate_is_published": True}

    async def set_as_target(
        self, owner_id: uuid.UUID, posting_id: uuid.UUID
    ) -> tuple[OwnPostingView, uuid.UUID | None]:
        return _own("Staff Engineer", status="running"), self.target_run

    async def own_postings(self, owner_id: uuid.UUID) -> list[OwnPostingView]:
        return [_own("Staff Engineer", status="ready", fit=64)]

    async def remove_own_posting(self, owner_id: uuid.UUID, posting_id: uuid.UUID) -> None:
        self.removed.append(posting_id)


class FakeActivity:
    """Counts build requests: a posting of the user's own must make none."""

    def __init__(self) -> None:
        self.requests = 0

    async def request_role_map(self, owner_id: uuid.UUID) -> None:
        self.requests += 1


@pytest.fixture
def target() -> FakeTarget:
    return FakeTarget()


@pytest.fixture
def activity() -> FakeActivity:
    return FakeActivity()


@pytest.fixture
def queued(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def enqueue(name: str, **kwargs: Any) -> None:
        calls.append({"name": name, **kwargs})

    monkeypatch.setattr(target_api, "enqueue", enqueue)
    return calls


@pytest.fixture
def client(target: FakeTarget, activity: FakeActivity, queued: list[Any]) -> TestClient:
    app = FastAPI()
    errors.install(app)
    app.include_router(target_api.router)
    user = uuid.uuid4()
    app.dependency_overrides[current_user] = lambda: user
    app.dependency_overrides[get_container] = lambda: SimpleNamespace(
        target=target, activity=activity, limiter=FakeLimiter(), limits=LIMITS
    )
    return TestClient(app, raise_server_exceptions=False)


def test_a_role_filled_in_by_hand_is_stored_and_spends_nothing(
    client: TestClient,
    target: FakeTarget,
    activity: FakeActivity,
    queued: list[dict[str, Any]],
) -> None:
    response = client.post(
        "/own-postings",
        json={
            "title": "Staff Engineer",
            "company_name": "Northwind",
            "requirements": ["Own the ledger", "Lead incident reviews"],
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert (body["private_job_posting_id"], body["status"]) == (str(JD_ID), None)
    assert body["source"] == "filled_in"
    assert target.added == [
        {
            "title": "Staff Engineer",
            "company_name": "Northwind",
            "requirements": ("Own the ledger", "Lead incident reviews"),
        }
    ]
    assert queued == []
    assert activity.requests == 0


def test_a_role_filled_in_by_hand_may_list_nothing(client: TestClient, target: FakeTarget) -> None:
    assert client.post("/own-postings", json={"title": "Platform Lead"}).status_code == 201
    assert target.added[0]["requirements"] == ()


@pytest.mark.parametrize(
    "body",
    [
        {"title": ""},
        {"company_name": "Northwind"},
        {"title": "x" * 256},
        {"title": "Staff Engineer", "requirements": ["x" * 501]},
        {"title": "Staff Engineer", "requirements": ["r"] * 31},
    ],
)
def test_a_role_filled_in_by_hand_needs_a_title_and_short_requirements(
    client: TestClient, target: FakeTarget, body: dict[str, Any]
) -> None:
    assert client.post("/own-postings", json=body).status_code == 422
    assert target.added == []


def test_the_postings_of_your_own_are_listed_with_their_fit(client: TestClient) -> None:
    body = client.get("/own-postings").json()

    assert body["total"] == 1
    assert (body["items"][0]["status"], body["items"][0]["fit"]) == ("ready", 64)


def test_setting_one_as_the_target_is_priced_first(client: TestClient) -> None:
    response = client.get(f"/own-postings/{JD_ID}/target-estimate")

    assert response.status_code == 200
    assert response.json() == {
        "cost_usd": "0.18",
        "model_id": "claude-opus-5",
        "rate_is_published": True,
    }


@pytest.mark.parametrize("run", [RUN_ID, None])
def test_setting_one_as_the_target_queues_its_scoring_unless_there_is_nothing_to_do(
    client: TestClient,
    target: FakeTarget,
    activity: FakeActivity,
    queued: list[dict[str, Any]],
    run: uuid.UUID | None,
) -> None:
    target.target_run = run

    response = client.post(f"/own-postings/{JD_ID}/target")

    assert response.status_code == 202
    assert [c["name"] for c in queued] == (["target.evaluate_own_posting"] if run else [])
    if run:
        assert queued[0]["evaluation_id"] == str(RUN_ID)
    assert activity.requests == 0


def test_the_old_paths_are_gone(client: TestClient) -> None:
    assert client.post("/own-postings/cost-estimate", json={}).status_code in (404, 405)
    assert client.post("/own-postings/upload-estimate", json={}).status_code in (404, 405)
    assert client.get(f"/own-postings/{JD_ID}/rescore-estimate").status_code == 404
    assert client.post(f"/own-postings/{JD_ID}/rescore").status_code == 404


def test_a_posting_of_your_own_is_removed(client: TestClient, target: FakeTarget) -> None:
    assert client.delete(f"/own-postings/{JD_ID}").status_code == 204
    assert target.removed == [JD_ID]


def test_an_uploaded_file_is_handed_over_as_it_came_and_spends_nothing(
    client: TestClient,
    target: FakeTarget,
    activity: FakeActivity,
    queued: list[dict[str, Any]],
) -> None:
    response = client.post(
        "/own-postings/upload",
        data={"title": "Staff Engineer", "company_name": "Northwind"},
        files={"file": ("jd.pdf", b"%PDF-1.7 ...", "application/pdf")},
    )

    assert response.status_code == 201
    assert response.json()["status"] is None
    assert target.uploaded == [
        {
            "title": "Staff Engineer",
            "company_name": "Northwind",
            "filename": "jd.pdf",
            "content_type": "application/pdf",
            "content": b"%PDF-1.7 ...",
        }
    ]
    assert queued == []
    assert activity.requests == 0


def test_an_upload_needs_no_title(client: TestClient, target: FakeTarget) -> None:
    response = client.post(
        "/own-postings/upload",
        files={"file": ("principal-engineer.txt", b"Own the ledger.", "text/plain")},
    )

    assert response.status_code == 201
    assert target.uploaded[0]["title"] is None


def test_an_upload_refuses_an_overlong_title(client: TestClient, target: FakeTarget) -> None:
    response = client.post(
        "/own-postings/upload",
        data={"title": "x" * 256},
        files={"file": ("jd.txt", b"Own the ledger.", "text/plain")},
    )

    assert response.status_code == 422
    assert target.uploaded == []


def test_an_upload_needs_its_file(client: TestClient, target: FakeTarget) -> None:
    assert client.post("/own-postings/upload", data={"title": "Staff"}).status_code == 422
    assert target.uploaded == []
