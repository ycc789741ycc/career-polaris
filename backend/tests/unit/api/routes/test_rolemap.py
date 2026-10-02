"""The role map at the HTTP edge: its estimate with the fits it is scored with
(ADR 0024), the candidates it comes from, a rebuild queued once, or left
waiting for an analysis (ADR 0018), and the postings the user brings
themselves (Phase 8).

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

from advisor.rolemap import (
    BuildRequestView,
    BuildRunView,
    FitView,
    OwnPostingView,
    RoleCandidateView,
    RoleView,
)
from api import errors
from api.dependencies import current_user, get_container
from api.routes import rolemap as rolemap_api
from wiring import queue


class FakeRoleMap:
    def __init__(self) -> None:
        self.added: list[dict[str, Any]] = []
        self.removed: list[uuid.UUID] = []
        self.finished: BuildRunView | None = None
        # How many recommended roles each fits estimate was asked to price.
        self.priced: list[dict[str, Any]] = []
        self.matched_for: list[uuid.UUID | None] = []
        self.one_per_company: list[bool | None] = []
        self.rescore_run: uuid.UUID | None = RUN_ID

    async def estimate_fits(self, owner_id: uuid.UUID, **kw: Any) -> dict[str, Any]:
        self.priced.append(kw)
        return {"cost_usd": "0.30", "roles": 10, "rate_is_published": True}

    async def fits(self, owner_id: uuid.UUID) -> list[FitView]:
        return [
            FitView(
                role_id=ROLE_ID,
                score=72,
                reasoning="Close on services.",
                gaps=(
                    {
                        "dimension_key": "backend",
                        "user_score": 60,
                        "target_score": 80,
                        "delta": -20,
                    },
                ),
                uncovered=({"statement": "Kubernetes", "weight": 0.5},),
                model_id="claude-opus-5",
                created_at=datetime(2026, 10, 3, 9, 0, tzinfo=UTC),
            )
        ]

    async def matched_postings(
        self,
        owner_id: uuid.UUID,
        *,
        limit: int | None,
        role_id: uuid.UUID | None,
        one_per_company: bool | None = None,
    ) -> list[Any]:
        self.matched_for.append(role_id)
        self.one_per_company.append(one_per_company)
        return []

    async def last_finished_build(self, owner_id: uuid.UUID) -> BuildRunView | None:
        return self.finished

    async def estimate_cost(self, owner_id: uuid.UUID) -> dict[str, Any]:
        return {"max_roles": 10, "cost_usd": "0.40", "model_id": "claude-opus-5"}

    async def estimate_own_posting(self, owner_id: uuid.UUID, **kw: Any) -> dict[str, Any]:
        return {"cost_usd": "0.18", "model_id": "claude-opus-5", "rate_is_published": True}

    async def add_own_posting(
        self, owner_id: uuid.UUID, **kw: Any
    ) -> tuple[OwnPostingView, uuid.UUID]:
        self.added.append(kw)
        return _own(kw["title"], status="running"), RUN_ID

    async def rescore_own_posting(
        self, owner_id: uuid.UUID, posting_id: uuid.UUID
    ) -> tuple[OwnPostingView, uuid.UUID | None]:
        return _own("Staff Engineer", status="running"), self.rescore_run

    async def own_postings(self, owner_id: uuid.UUID) -> list[OwnPostingView]:
        return [_own("Staff Engineer", status="ready", fit=64)]

    async def remove_own_posting(self, owner_id: uuid.UUID, posting_id: uuid.UUID) -> None:
        self.removed.append(posting_id)

    async def map_roles(self, owner_id: uuid.UUID) -> list[RoleView]:
        """The roles as drawn: counted live, two openings left of the five the
        build stored."""
        return [_role(opening_count=2)]

    async def roles(self, owner_id: uuid.UUID) -> list[RoleView]:
        return [_role(opening_count=5)]

    async def candidates(self, owner_id: uuid.UUID) -> list[RoleCandidateView]:
        return [
            RoleCandidateView(
                id=uuid.UUID(int=rank + 1),
                rank=rank,
                title=title,
                description="The work.",
                dimension_keys=("backend",),
                role_id=role_id,
                opening_count=4 if role_id else 0,
            )
            for rank, (title, role_id) in enumerate(
                [("Backend Engineer", ROLE_ID), ("Payments Engineer", None)]
            )
        ]


ROLE_ID = uuid.uuid4()
JD_ID = uuid.uuid4()
RUN_ID = uuid.uuid4()


def _own(title: str, *, status: str, fit: int | None = None) -> OwnPostingView:
    return OwnPostingView(
        private_job_posting_id=JD_ID,
        title=title,
        company_name="Northwind",
        status=status,
        error_code=None,
        error_message=None,
        fit=fit,
        is_stale=False,
        scored_at=None,
    )


def _role(*, opening_count: int) -> RoleView:
    return RoleView(
        id=ROLE_ID,
        name="Backend Engineer",
        hiring_bar=60,
        bar_basis="estimated",
        bar_confidence=0.5,
        bar_reasoning=None,
        opening_count=opening_count,
        salary_bands={},
        requirements=(),
        is_coherent=True,
    )


class FakeMarket:
    def __init__(self) -> None:
        self.locations = ["Remote", "Taiwan"]

    async def target_locations(self, owner_id: uuid.UUID) -> list[str]:
        return self.locations


class FakeActivity:
    """Answers every build request the same way, and counts them."""

    def __init__(self) -> None:
        self.status = "running"
        self.should_queue = True
        self.should_await_market = False
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
        return BuildRequestView(
            build=build,
            should_queue=self.should_queue,
            should_await_market=self.should_await_market,
        )


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

    async def enqueue_later(name: str, *, seconds: int, **kwargs: Any) -> None:
        calls.append({"name": name, **kwargs})

    # The route hands every build request to wiring's one helper, which queues
    # it or schedules its check on the market (ADR 0027).
    monkeypatch.setattr(queue, "enqueue", enqueue)
    # Scoring fits on request queues its job directly.
    monkeypatch.setattr(rolemap_api, "enqueue", enqueue)
    monkeypatch.setattr(queue, "enqueue_later", enqueue_later)
    monkeypatch.setattr(queue, "get_settings", lambda: SimpleNamespace(crawl_due_poll_seconds=15))
    return calls


@pytest.fixture
def client(
    rolemap: FakeRoleMap,
    activity: FakeActivity,
    market: FakeMarket,
    queued: list[Any],
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


def test_the_estimate_prices_the_ten_recommended_roles_and_their_fits(
    client: TestClient, rolemap: FakeRoleMap
) -> None:
    response = client.get("/roles/cost-estimate")
    assert response.status_code == 200
    assert response.json() == {
        "cost_usd": "0.70",
        "model_id": "claude-opus-5",
        "max_roles": 10,
        "fits_cost_usd": "0.30",
        "rate_is_published": True,
    }
    assert rolemap.priced == [{"recommended": 10}]


def test_the_candidates_say_which_ones_the_market_had(client: TestClient) -> None:
    response = client.get("/role-candidates")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert [(c["title"], c["role_id"]) for c in body["items"]] == [
        ("Backend Engineer", str(ROLE_ID)),
        ("Payments Engineer", None),
    ]


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


# --- postings of the user's own (Phase 8) -------------------------------------


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
    rolemap: FakeRoleMap,
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
    assert rolemap.added == [
        {
            "title": "Staff Engineer",
            "company_name": "Northwind",
            "job_description": "Own the ledger.",
        }
    ]
    assert [c["name"] for c in queued] == ["rolemap.evaluate_own_posting"]
    assert queued[0]["evaluation_id"] == str(RUN_ID)
    assert activity.requests == 0


@pytest.mark.parametrize(
    "body", [{"title": "", "job_description": "JD"}, {"title": "Staff Engineer"}]
)
def test_a_posting_of_your_own_needs_a_title_and_a_jd(
    client: TestClient, rolemap: FakeRoleMap, body: dict[str, str]
) -> None:
    assert client.post("/own-postings", json=body).status_code == 422
    assert rolemap.added == []


def test_the_postings_of_your_own_are_listed_with_their_fit(client: TestClient) -> None:
    body = client.get("/own-postings").json()

    assert body["total"] == 1
    assert (body["items"][0]["status"], body["items"][0]["fit"]) == ("ready", 64)


@pytest.mark.parametrize("run", [RUN_ID, None])
def test_a_rescore_is_queued_unless_one_is_already_running(
    client: TestClient, rolemap: FakeRoleMap, queued: list[dict[str, Any]], run: uuid.UUID | None
) -> None:
    rolemap.rescore_run = run

    response = client.post(f"/own-postings/{JD_ID}/rescore")

    assert response.status_code == 202
    assert [c["name"] for c in queued] == (["rolemap.evaluate_own_posting"] if run else [])


def test_a_posting_of_your_own_is_removed(client: TestClient, rolemap: FakeRoleMap) -> None:
    assert client.delete(f"/own-postings/{JD_ID}").status_code == 204
    assert rolemap.removed == [JD_ID]


def test_there_are_no_custom_roles_to_add(client: TestClient) -> None:
    assert client.post("/roles/custom", json={"title": "Staff"}).status_code in (404, 405)


def test_a_rebuild_waiting_for_the_market_schedules_its_check_and_says_so(
    client: TestClient, activity: FakeActivity, queued: list[dict[str, Any]]
) -> None:
    activity.status, activity.should_queue, activity.should_await_market = "waiting", False, True

    response = client.post("/roles/recluster")

    assert response.status_code == 202
    assert [c["name"] for c in queued] == ["rolemap.await_market"]


def _finished(locations: tuple[str, ...], needed: tuple[uuid.UUID, ...]) -> BuildRunView:
    at = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
    return BuildRunView(
        id=uuid.uuid4(),
        status="ready",
        requested_at=at,
        started_at=at,
        finished_at=at,
        error_code=None,
        error_message=None,
        locations=locations,
        needed_source_ids=needed,
        market_data_at=datetime(2026, 9, 30, 12, 0, tzinfo=UTC),
    )


def test_the_map_says_how_old_its_market_is_and_whether_the_locations_moved(
    client: TestClient, rolemap: FakeRoleMap, market: FakeMarket
) -> None:
    rolemap.finished = _finished(("Taiwan", "Remote"), (uuid.uuid4(),))

    current = client.get("/role-map").json()
    market.locations = ["Taiwan"]
    moved = client.get("/role-map").json()

    assert current == {
        "market_data_at": "2026-09-30T12:00:00+00:00",
        "built_for_locations": ["Taiwan", "Remote"],
        "locations_changed": False,
    }
    assert moved["locations_changed"] is True


@pytest.mark.parametrize("finished", [None, "before ADR 0027"])
def test_with_no_map_or_one_from_before_there_is_nothing_to_say(
    client: TestClient, rolemap: FakeRoleMap, finished: str | None
) -> None:
    rolemap.finished = None if finished is None else _finished((), ())

    assert client.get("/role-map").json() == {
        "market_data_at": None,
        "built_for_locations": None,
        "locations_changed": False,
    }


# --- fits and the openings inside the roles (ADR 0028) -----------------------


def test_fits_are_the_role_maps_and_answer_as_a_page(client: TestClient) -> None:
    response = client.get("/fits")

    assert response.status_code == 200
    [fit] = response.json()["items"]
    assert (fit["role_id"], fit["score"]) == (str(ROLE_ID), 72)
    assert fit["gaps"] == [
        {"dimension_key": "backend", "user_score": 60, "target_score": 80, "delta": -20}
    ]
    assert "private_posting_id" not in fit


def test_scoring_fits_queues_the_role_maps_job(
    client: TestClient, queued: list[dict[str, Any]]
) -> None:
    response = client.post("/fits/compute")

    assert response.status_code == 202
    assert [call["name"] for call in queued] == ["rolemap.compute_fits"]


def test_matched_postings_can_be_narrowed_to_one_role(
    client: TestClient, rolemap: FakeRoleMap
) -> None:
    response = client.get("/matched-postings", params={"role_id": str(ROLE_ID)})

    assert response.status_code == 200
    assert response.json()["items"] == []
    assert rolemap.matched_for == [ROLE_ID]
    assert rolemap.one_per_company == [None]


def test_top_matched_asks_for_one_opening_per_company_in_the_selected_role(
    client: TestClient, rolemap: FakeRoleMap
) -> None:
    response = client.get(
        "/matched-postings",
        params={"role_id": str(ROLE_ID), "one_per_company": "true", "page_size": 10},
    )

    assert response.status_code == 200
    assert (rolemap.matched_for, rolemap.one_per_company) == ([ROLE_ID], [True])


def test_the_roles_are_drawn_with_the_openings_they_have_now(client: TestClient) -> None:
    """A bubble's count is what Top matched can list for it, not the build's."""
    response = client.get("/roles")

    assert response.status_code == 200
    [role] = response.json()["items"]
    assert (role["id"], role["opening_count"]) == (str(ROLE_ID), 2)
