"""The outbox dispatcher: submitted answers into nothing at all (ADR 0035),
finished analyses into the role-map builds that follow them (ADR 0018, 0020),
and finished builds into one scoring of the fits (ADR 0024). Nothing the
market does, and no change of locations, builds a map (ADR 0027).

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

    async def queue_build(owner_id: uuid.UUID, requested: Any) -> None:
        calls.append({"name": "queue_build", "owner_id": owner_id, "requested": requested})

    monkeypatch.setattr(dispatcher, "enqueue", enqueue)
    monkeypatch.setattr(dispatcher, "queue_build", queue_build)
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


@pytest.mark.parametrize(
    ("role", "opening", "own"), [("r1", None, None), ("r1", "p1", None), (None, None, "o1")]
)
async def test_submitted_answers_rewrite_nothing(
    role: str | None, opening: str | None, own: str | None, queued: list[dict[str, Any]]
) -> None:
    """Answering spends nothing: the Target's plan and résumé read as outdated,
    and the user regenerates them at a price they confirm (ADR 0035)."""
    event = OutboxEvent(
        name=str(EventName.GAP_ANSWERS_SUBMITTED),
        owner_id=OWNER,
        payload={
            "set_id": str(uuid.uuid4()),
            "role_id": role,
            "job_posting_id": opening,
            "private_job_posting_id": own,
            "evidence_ids": ["e1"],
        },
    )

    await dispatcher._handle(_container(), event)

    assert queued == []


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
    requested = SimpleNamespace(build=SimpleNamespace(id=uuid.uuid4()), should_queue=True)
    activity = FakeActivity(released=requested)

    await dispatcher._handle(_container(activity=activity), _analysis_finished(status))

    assert activity.releases == [(OWNER, succeeded)]
    # Queued, or set waiting for the market, by the one helper the routes use too.
    assert queued == [{"name": "queue_build", "owner_id": OWNER, "requested": requested}]


async def test_a_finished_analysis_queues_nothing_when_there_is_no_build_to_start(
    queued: list[dict[str, Any]],
) -> None:
    activity = FakeActivity(released=None)

    await dispatcher._handle(_container(activity=activity), _analysis_finished("failed"))

    assert activity.releases == [(OWNER, False)] and queued == []


class FakeRoleMap:
    """The roles the user's last analysis recommended."""

    def __init__(self, titles: list[str] | None = None) -> None:
        self.titles = titles or []

    async def candidates(self, owner_id: uuid.UUID) -> list[Any]:
        return [SimpleNamespace(title=title) for title in self.titles]


async def test_new_target_locations_build_nothing_and_search_nothing(
    queued: list[dict[str, Any]],
) -> None:
    """A build spends the user's key, so it waits until they ask; the next one
    searches the new places (ADR 0027)."""
    activity = FakeActivity()
    event = OutboxEvent(
        name=str(EventName.TARGET_LOCATIONS_CHANGED),
        owner_id=OWNER,
        payload={"locations": ["Taiwan", "Remote"]},
    )

    await dispatcher._handle(
        _container(activity=activity, rolemap=FakeRoleMap(["Data Engineer"])), event
    )

    assert activity.requests == [] and queued == []


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

    assert queued == [{"name": "rolemap.compute_fits", "owner_id": str(OWNER)}]


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
