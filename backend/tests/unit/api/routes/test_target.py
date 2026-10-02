"""Target at the HTTP edge: the postings the user brings themselves, priced
first, queued to be read and scored, listed, rescored and removed
(Phase 8, ADR 0033).

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

JD_ID = uuid.uuid4()
RUN_ID = uuid.uuid4()


def _own(title: str, *, status: str, fit: int | None = None) -> OwnPostingView:
    return OwnPostingView(
        private_job_posting_id=JD_ID,
        title=title,
        company_name="Northwind",
        source="pasted",
        filename=None,
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
        self.rescore_run: uuid.UUID | None = RUN_ID

    async def estimate_own_posting(self, owner_id: uuid.UUID, **kw: Any) -> dict[str, Any]:
        return {"cost_usd": "0.18", "model_id": "claude-opus-5", "rate_is_published": True}

    async def estimate_rescore(self, owner_id: uuid.UUID, posting_id: uuid.UUID) -> dict[str, Any]:
        return {"cost_usd": "0.09", "model_id": "claude-opus-5", "rate_is_published": True}

    async def add_own_posting(
        self, owner_id: uuid.UUID, **kw: Any
    ) -> tuple[OwnPostingView, uuid.UUID]:
        self.added.append(kw)
        return _own(kw["title"], status="running"), RUN_ID

    async def estimate_upload(self, owner_id: uuid.UUID, **kw: Any) -> dict[str, Any]:
        return {"cost_usd": "0.22", "model_id": "claude-opus-5", "rate_is_published": True}

    async def upload_own_posting(
        self, owner_id: uuid.UUID, **kw: Any
    ) -> tuple[OwnPostingView, uuid.UUID]:
        self.uploaded.append(kw)
        return _own(kw["title"], status="running"), RUN_ID

    async def rescore_own_posting(
        self, owner_id: uuid.UUID, posting_id: uuid.UUID
    ) -> tuple[OwnPostingView, uuid.UUID | None]:
        return _own("Staff Engineer", status="running"), self.rescore_run

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
        target=target, activity=activity
    )
    return TestClient(app, raise_server_exceptions=False)


def test_a_posting_of_your_own_is_priced_first(client: TestClient) -> None:
    response = client.post(
        "/own-postings/cost-estimate",
        json={"title": "Staff Engineer", "job_description": "Own the ledger."},
    )

    assert response.status_code == 200
    assert response.json() == {
        "cost_usd": "0.18",
        "model_id": "claude-opus-5",
        "rate_is_published": True,
    }


def test_a_posting_of_your_own_is_queued_to_be_scored_and_builds_nothing(
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
            "job_description": "Own the ledger.",
        },
    )

    assert response.status_code == 202
    body = response.json()
    assert (body["private_job_posting_id"], body["status"]) == (str(JD_ID), "running")
    assert target.added == [
        {
            "title": "Staff Engineer",
            "company_name": "Northwind",
            "job_description": "Own the ledger.",
        }
    ]
    assert [c["name"] for c in queued] == ["target.evaluate_own_posting"]
    assert queued[0]["evaluation_id"] == str(RUN_ID)
    assert activity.requests == 0


@pytest.mark.parametrize(
    "body",
    [
        {"title": "", "job_description": "JD"},
        {"title": "Staff Engineer"},
        {"title": "x" * 256, "job_description": "JD"},
        {"title": "Staff Engineer", "job_description": "x" * 50_001},
    ],
)
def test_a_posting_of_your_own_needs_a_title_and_a_jd(
    client: TestClient, target: FakeTarget, body: dict[str, str]
) -> None:
    assert client.post("/own-postings", json=body).status_code == 422
    assert target.added == []


def test_the_postings_of_your_own_are_listed_with_their_fit(client: TestClient) -> None:
    body = client.get("/own-postings").json()

    assert body["total"] == 1
    assert (body["items"][0]["status"], body["items"][0]["fit"]) == ("ready", 64)


def test_a_rescore_is_priced_first(client: TestClient) -> None:
    response = client.get(f"/own-postings/{JD_ID}/rescore-estimate")

    assert response.status_code == 200
    assert response.json()["cost_usd"] == "0.09"


@pytest.mark.parametrize("run", [RUN_ID, None])
def test_a_rescore_is_queued_unless_one_is_already_running(
    client: TestClient, target: FakeTarget, queued: list[dict[str, Any]], run: uuid.UUID | None
) -> None:
    target.rescore_run = run

    response = client.post(f"/own-postings/{JD_ID}/rescore")

    assert response.status_code == 202
    assert [c["name"] for c in queued] == (["target.evaluate_own_posting"] if run else [])


def test_a_posting_of_your_own_is_removed(client: TestClient, target: FakeTarget) -> None:
    assert client.delete(f"/own-postings/{JD_ID}").status_code == 204
    assert target.removed == [JD_ID]


def test_an_upload_is_priced_from_its_title_alone(client: TestClient) -> None:
    response = client.post("/own-postings/upload-estimate", json={"title": "Staff Engineer"})

    assert response.status_code == 200
    assert response.json()["cost_usd"] == "0.22"


def test_an_uploaded_file_is_handed_over_as_it_came_and_queued_to_be_read(
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

    assert response.status_code == 202
    assert response.json()["status"] == "running"
    assert target.uploaded == [
        {
            "title": "Staff Engineer",
            "company_name": "Northwind",
            "filename": "jd.pdf",
            "content_type": "application/pdf",
            "content": b"%PDF-1.7 ...",
        }
    ]
    assert [c["name"] for c in queued] == ["target.evaluate_own_posting"]
    assert activity.requests == 0


@pytest.mark.parametrize(
    "form",
    [{"title": ""}, {}, {"title": "x" * 256}],
)
def test_an_upload_needs_a_title(
    client: TestClient, target: FakeTarget, form: dict[str, str]
) -> None:
    response = client.post(
        "/own-postings/upload",
        data=form,
        files={"file": ("jd.txt", b"Own the ledger.", "text/plain")},
    )

    assert response.status_code == 422
    assert target.uploaded == []


def test_an_upload_needs_its_file(client: TestClient, target: FakeTarget) -> None:
    assert client.post("/own-postings/upload", data={"title": "Staff"}).status_code == 422
    assert target.uploaded == []
