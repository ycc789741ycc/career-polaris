"""Market at the HTTP edge: target locations and pasted JDs on the wire.

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

from advisor.market import (
    MarketScopeView,
    PostingView,
    TargetLocationOptionView,
    Visibility,
)
from api import errors
from api.dependencies import current_user, get_container
from api.routes import market as market_api

POSTING_ID = uuid.uuid4()


class FakeMarket:
    def __init__(self) -> None:
        self.saved: list[list[str]] = []

    async def set_target_locations(self, owner_id: uuid.UUID, locations: list[str]) -> list[str]:
        self.saved.append(locations)
        return sorted(locations)

    async def scope(self, owner_id: uuid.UUID) -> MarketScopeView:
        return MarketScopeView(target_locations=["Germany", "Remote"], open_posting_count=1284)

    def target_location_options(self) -> list[TargetLocationOptionView]:
        return [
            TargetLocationOptionView(name="Remote", kind="remote"),
            TargetLocationOptionView(name="Europe", kind="region"),
            TargetLocationOptionView(name="Taiwan", kind="country"),
        ]

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
def market() -> FakeMarket:
    return FakeMarket()


@pytest.fixture
def client(market: FakeMarket) -> TestClient:
    app = FastAPI()
    errors.install(app)
    app.include_router(market_api.router)
    app.dependency_overrides[current_user] = lambda: uuid.uuid4()
    app.dependency_overrides[get_container] = lambda: SimpleNamespace(market=market)
    return TestClient(app)


def test_a_jd_is_added_with_a_custom_role_not_on_its_own(client: TestClient) -> None:
    response = client.post("/job-descriptions", json={"title": "Staff", "description": "JD"})

    assert response.status_code == 405


def test_target_locations_are_saved_as_a_whole_set(client: TestClient) -> None:
    response = client.put("/target-locations", json={"locations": ["Remote", "Germany"]})

    assert response.status_code == 200
    assert response.json() == ["Germany", "Remote"]


def test_the_places_to_pick_from_come_as_a_page_with_their_kinds(client: TestClient) -> None:
    response = client.get("/target-location-options")

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {"name": "Remote", "kind": "remote"},
            {"name": "Europe", "kind": "region"},
            {"name": "Taiwan", "kind": "country"},
        ],
        "page": 1,
        "page_size": None,
        "total": 3,
    }


def test_a_fourth_target_location_is_refused_before_the_service(
    client: TestClient, market: FakeMarket
) -> None:
    response = client.put(
        "/target-locations", json={"locations": ["Berlin", "Lisbon", "Paris", "Remote EU"]}
    )

    assert response.status_code == 422
    assert market.saved == []


def test_the_market_scope_says_how_many_postings_the_locations_take_in(
    client: TestClient,
) -> None:
    response = client.get("/market-scope")

    assert response.status_code == 200
    assert response.json() == {
        "target_locations": ["Germany", "Remote"],
        "open_posting_count": 1284,
    }
