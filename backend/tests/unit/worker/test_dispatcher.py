"""The outbox dispatcher: submitted answers into regenerations (ADR 0023),
finished analyses into the role-map builds that follow them (ADR 0018, 0020),
and finished builds into one scoring of the fits (ADR 0024).

Calls the dispatcher's handler directly with stand-in services and a recorded
queue — no database, no job runner.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from kernel.outbox import EventName, OutboxEvent
from worker import dispatcher

OWNER = uuid.UUID("00000000-0000-0000-0000-000000000001")


@pytest.fixture
def queued(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def enqueue(name: str, **kwargs: Any) -> None:
        calls.append({"name": name, **kwargs})

    monkeypatch.setattr(dispatcher, "enqueue", enqueue)
    return calls


def _profile_updated(source: str) -> OutboxEvent:
    return OutboxEvent(
        name=str(EventName.PROFILE_UPDATED),
        owner_id=OWNER,
        payload={"source": source, "version": 3, "count": 12},
    )


@pytest.mark.parametrize("source", ["github", "jira", "resume", "user_answer"])
async def test_new_evidence_spends_nothing(source: str, queued: list[dict[str, Any]]) -> None:
    """Questions come from a Target's gaps now, not from new evidence (ADR 0023)."""
    await dispatcher._handle(_container(), _profile_updated(source))

    assert queued == []


# --- Fill the gap (ADR 0023) -----------------------------------------------


@pytest.mark.parametrize("opening", [None, "p1"])
async def test_submitted_answers_regenerate_the_targets_plan_and_resume(
    opening: str | None, queued: list[dict[str, Any]]
) -> None:
    event = OutboxEvent(
        name=str(EventName.GAP_ANSWERS_SUBMITTED),
        owner_id=OWNER,
        payload={
            "set_id": str(uuid.uuid4()),
            "role_id": "r1",
            "job_posting_id": opening,
            "evidence_ids": ["e1"],
        },
    )

    await dispatcher._handle(_container(), event)

    target = {"owner_id": str(OWNER), "role_id": "r1", "job_posting_id": opening}
    assert queued == [
        {"name": "gapplan.regenerate", **target},
        {"name": "resume.regenerate", **target},
    ]


# --- role maps waiting on an analysis (ADR 0018) ---------------------------


class FakeActivity:
    def __init__(self, *, released: Any = None, requested: Any = None) -> None:
        self.released = released
        self.requested = requested
        self.releases: list[tuple[uuid.UUID, bool]] = []
        self.requests: list[uuid.UUID] = []

    async def build_after_analysis(self, owner_id: uuid.UUID, *, succeeded: bool) -> Any:
        self.releases.append((owner_id, succeeded))
        return self.released

    async def request_role_map(self, owner_id: uuid.UUID) -> Any:
        self.requests.append(owner_id)
        return self.requested

    async def rebuild_role_map(self, owner_id: uuid.UUID) -> Any:
        self.requests.append(owner_id)
        return self.requested


def _container(**services: Any) -> Any:
    return SimpleNamespace(**services)


def _analysis_finished(status: str) -> OutboxEvent:
    return OutboxEvent(
        name=str(EventName.ANALYSIS_FINISHED),
        owner_id=OWNER,
        payload={"run_id": str(uuid.uuid4()), "status": status, "error_code": None},
    )


@pytest.mark.parametrize(("status", "succeeded"), [("ready", True), ("failed", False)])
async def test_a_finished_analysis_queues_the_build_activity_hands_back(
    status: str, succeeded: bool, queued: list[dict[str, Any]]
) -> None:
    build_id = uuid.uuid4()
    activity = FakeActivity(released=SimpleNamespace(id=build_id))

    await dispatcher._handle(_container(activity=activity), _analysis_finished(status))

    assert activity.releases == [(OWNER, succeeded)]
    assert queued == [
        {"name": "rolemap.recluster", "owner_id": str(OWNER), "build_id": str(build_id)}
    ]


async def test_a_finished_analysis_queues_nothing_when_there_is_no_build_to_start(
    queued: list[dict[str, Any]],
) -> None:
    activity = FakeActivity(released=None)

    await dispatcher._handle(_container(activity=activity), _analysis_finished("failed"))

    assert activity.releases == [(OWNER, False)] and queued == []


@pytest.mark.parametrize(("should_queue", "expected"), [(True, 1), (False, 0)])
async def test_new_postings_rebuild_only_a_role_map_that_is_not_waiting_or_running(
    should_queue: bool,
    expected: int,
    queued: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def affected(deps: Any, payload: dict[str, Any]) -> list[uuid.UUID]:
        return [OWNER]

    monkeypatch.setattr(dispatcher, "_users_affected_by", affected)
    build = SimpleNamespace(id=uuid.uuid4())
    activity = FakeActivity(requested=SimpleNamespace(build=build, should_queue=should_queue))
    event = OutboxEvent(name=str(EventName.POSTINGS_CHANGED), owner_id=None, payload={})

    await dispatcher._handle(_container(activity=activity), event)

    assert activity.requests == [OWNER] and len(queued) == expected


def _target_locations_changed() -> OutboxEvent:
    return OutboxEvent(
        name=str(EventName.TARGET_LOCATIONS_CHANGED),
        owner_id=OWNER,
        payload={"locations": ["Berlin", "Remote EU"]},
    )


async def test_new_target_locations_rebuild_the_role_map_on_the_new_scope(
    queued: list[dict[str, Any]],
) -> None:
    build = SimpleNamespace(id=uuid.uuid4())
    activity = FakeActivity(requested=SimpleNamespace(build=build, should_queue=True))

    await dispatcher._handle(_container(activity=activity), _target_locations_changed())

    assert activity.requests == [OWNER]
    assert queued == [
        {"name": "rolemap.recluster", "owner_id": str(OWNER), "build_id": str(build.id)}
    ]


async def test_new_target_locations_queue_nothing_without_a_role_map_to_rebuild(
    queued: list[dict[str, Any]],
) -> None:
    activity = FakeActivity(requested=None)

    await dispatcher._handle(_container(activity=activity), _target_locations_changed())

    assert activity.requests == [OWNER] and queued == []


class FakeMarket:
    def __init__(self) -> None:
        self.named: list[str] = []
        self.company_id = uuid.uuid4()

    async def company_named(self, name: str) -> uuid.UUID:
        self.named.append(name)
        return self.company_id


def _custom_role_added(company_name: str | None) -> OutboxEvent:
    return OutboxEvent(
        name=str(EventName.CUSTOM_ROLE_ADDED),
        owner_id=OWNER,
        payload={"role_id": str(uuid.uuid4()), "company_name": company_name},
    )


async def test_a_custom_roles_company_goes_to_board_discovery_without_its_owner(
    queued: list[dict[str, Any]],
) -> None:
    market = FakeMarket()

    await dispatcher._handle(_container(market=market), _custom_role_added("Northwind"))

    assert market.named == ["Northwind"]
    assert queued == [
        {
            "name": "market.discover_board",
            "company_id": str(market.company_id),
            "company_name": "Northwind",
        }
    ]


async def test_a_custom_role_with_no_company_seeds_nothing(queued: list[dict[str, Any]]) -> None:
    market = FakeMarket()

    await dispatcher._handle(_container(market=market), _custom_role_added(None))

    assert market.named == [] and queued == []


# --- Fits, once per build (ADR 0024) ---------------------------------------


@pytest.mark.parametrize("status", ["ready", "failed"])
async def test_a_closed_build_scores_the_fits_once(
    status: str, queued: list[dict[str, Any]]
) -> None:
    event = OutboxEvent(
        name=str(EventName.ROLE_MAP_BUILD_FINISHED),
        owner_id=OWNER,
        payload={"build_id": str(uuid.uuid4()), "status": status},
    )

    await dispatcher._handle(_container(), event)

    assert queued == [{"name": "assessment.compute_fits", "owner_id": str(OWNER)}]


@pytest.mark.parametrize(
    "name",
    [
        EventName.ASSESSMENT_COMPLETED,
        EventName.DIMENSIONS_CHANGED,
        EventName.ROLE_REQUIREMENTS_CHANGED,
    ],
)
async def test_scores_and_requirements_changing_do_not_score_fits_on_their_own(
    name: EventName, queued: list[dict[str, Any]]
) -> None:
    """Each would score every role again, just before the build replaces them;
    the build that follows scores them once when it closes."""
    await dispatcher._handle(_container(), OutboxEvent(name=str(name), owner_id=OWNER, payload={}))

    assert queued == []
