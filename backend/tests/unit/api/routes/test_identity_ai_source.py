"""Which key AI runs on, at the HTTP edge (ADR 0064): the choice, and this
month's quota on CareerPolaris's key.

Runs the real router and error handlers in-process against a stand-in
identity service and meter — no network, no infra.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from advisor.identity import AiSource, AiSourceView
from api import errors
from api.dependencies import current_user, get_container
from api.routes import identity as identity_api
from kernel.errors import PlatformAiNotEligibleError
from kernel.limits import SpendState

OWNER = uuid.UUID("22222222-2222-2222-2222-222222222222")


def _view(source: AiSource | None) -> AiSourceView:
    return AiSourceView(
        source=source,
        has_credential=False,
        is_platform_on=True,
        is_eligible=True,
    )


class FakeIdentity:
    def __init__(self) -> None:
        self.asked: list[str] = []
        self.refuse: Exception | None = None

    async def ai_source(self, owner_id: uuid.UUID) -> AiSourceView:
        return _view(None)

    async def set_ai_source(self, owner_id: uuid.UUID, *, source: str) -> AiSourceView:
        if self.refuse is not None:
            raise self.refuse
        self.asked.append(source)
        return _view(AiSource(source))


class FakeSpend:
    async def get_account_state(self, owner_id: uuid.UUID) -> SpendState:
        return SpendState(
            allowed_usd=Decimal("2"), spent_usd=Decimal("0.5"), reserved_usd=Decimal("0.25")
        )


@pytest.fixture
def identity() -> FakeIdentity:
    return FakeIdentity()


def _client(identity: FakeIdentity, spend: FakeSpend | None) -> TestClient:
    app = FastAPI()
    errors.install(app)
    app.include_router(identity_api.router)
    app.dependency_overrides[current_user] = lambda: OWNER
    app.dependency_overrides[get_container] = lambda: SimpleNamespace(
        identity=identity, platform_spend=spend
    )
    return TestClient(app)


def test_the_choice_comes_with_this_months_quota(identity: FakeIdentity) -> None:
    body = _client(identity, FakeSpend()).get("/ai-source").json()

    assert body["source"] is None
    # The platform's model is never told to the client (ADR 0066).
    assert "platform_model" not in body
    assert body["platform_quota"] == {
        "allowed_usd": "2",
        "spent_usd": "0.5",
        "remaining_usd": "1.25",
    }


def test_with_the_platform_off_there_is_no_quota(identity: FakeIdentity) -> None:
    body = _client(identity, None).get("/ai-source").json()

    assert body["platform_quota"] is None


def test_switching_needs_only_the_source(identity: FakeIdentity) -> None:
    response = _client(identity, FakeSpend()).put("/ai-source", json={"source": "platform"})

    assert response.status_code == 200
    assert response.json()["source"] == "platform"
    assert identity.asked == ["platform"]


def test_an_unknown_source_is_refused_at_the_edge(identity: FakeIdentity) -> None:
    response = _client(identity, FakeSpend()).put("/ai-source", json={"source": "borrowed"})

    assert response.status_code == 422
    assert identity.asked == []


def test_an_account_google_has_not_verified_is_told_so(identity: FakeIdentity) -> None:
    identity.refuse = PlatformAiNotEligibleError("for accounts signed in with Google")

    response = _client(identity, FakeSpend()).put("/ai-source", json={"source": "platform"})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ai_platform_not_eligible"
