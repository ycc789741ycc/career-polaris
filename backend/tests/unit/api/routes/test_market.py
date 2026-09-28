"""Market at the HTTP edge: watched roles and pasted JDs on the wire.

Runs the real router and error handlers in-process against a stand-in service —
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

from advisor.market import CompanySubscriptionView, Coverage, PostingView, Visibility
from api import errors
from api.dependencies import current_user, get_container
from api.routes import market as market_api

SUBSCRIPTION_ID = uuid.uuid4()
COMPANY_ID = uuid.uuid4()
POSTING_ID = uuid.uuid4()


def _subscription(**overrides: Any) -> CompanySubscriptionView:
    fields: dict[str, Any] = {
        "id": SUBSCRIPTION_ID,
        "company_id": COMPANY_ID,
        "company_name": "Meridian Labs",
        "role_title": "Staff Platform Engineer",
        "role_id": None,
        "url": "https://meridian.example/careers",
        "coverage": Coverage.MANUAL,
        "last_refreshed_at": None,
    }
    return CompanySubscriptionView(**(fields | overrides))


class FakeMarket:
    async def subscriptions(self, owner_id: uuid.UUID) -> list[CompanySubscriptionView]:
        return [_subscription(last_refreshed_at=datetime(2026, 9, 21, tzinfo=UTC))]

    async def subscribe(self, owner_id: uuid.UUID, **_: Any) -> CompanySubscriptionView:
        return _subscription()

    async def paste_job_description(self, owner_id: uuid.UUID, **kw: Any) -> PostingView:
        return PostingView(
            id=POSTING_ID,
            company_name=kw["company_name"],
            title=kw["title"],
            location=kw["location"],
            url=kw["url"],
            description=kw["description"],
            visibility=Visibility.PRIVATE,
            salary=None,
        )


@pytest.fixture
def queued(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def enqueue(name: str, **kwargs: Any) -> None:
        calls.append({"name": name, **kwargs})

    monkeypatch.setattr(market_api, "enqueue", enqueue)
    return calls


@pytest.fixture
def client(queued: list[dict[str, Any]]) -> TestClient:
    app = FastAPI()
    errors.install(app)
    app.include_router(market_api.router)
    app.dependency_overrides[current_user] = lambda: uuid.uuid4()
    app.dependency_overrides[get_container] = lambda: SimpleNamespace(market=FakeMarket())
    return TestClient(app)


def test_a_watched_role_says_plainly_when_nothing_updates_it(client: TestClient) -> None:
    assert client.get("/role-subscriptions").json() == [
        {
            "id": str(SUBSCRIPTION_ID),
            "company_id": str(COMPANY_ID),
            "company_name": "Meridian Labs",
            "role_title": "Staff Platform Engineer",
            "role_id": None,
            "url": "https://meridian.example/careers",
            "coverage": "manual",
            "last_refreshed_at": "2026-09-21T00:00:00+00:00",
        }
    ]


def test_watching_a_role_queues_board_discovery(
    client: TestClient, queued: list[dict[str, Any]]
) -> None:
    response = client.post(
        "/role-subscriptions",
        json={"company_name": "Meridian Labs", "role_title": "Staff Platform Engineer"},
    )

    assert response.status_code == 201
    assert response.json()["id"] == str(SUBSCRIPTION_ID)
    assert [c["name"] for c in queued] == ["market.discover_board"]


def test_a_pasted_jd_comes_back_private(client: TestClient) -> None:
    response = client.post(
        "/job-descriptions",
        json={
            "company_name": "Meridian Labs",
            "title": "Staff Platform Engineer",
            "location": "Remote",
            "description": "Run our platform.",
        },
    )

    assert response.status_code == 201
    assert response.json() == {
        "id": str(POSTING_ID),
        "company_name": "Meridian Labs",
        "title": "Staff Platform Engineer",
        "location": "Remote",
        "visibility": "private",
    }
