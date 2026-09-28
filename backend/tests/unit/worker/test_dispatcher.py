"""The outbox dispatcher turning evidence changes into question rounds (ADR 0012),
and finished analyses into the role-map builds that waited for them (ADR 0018).

Calls the dispatcher's handler directly with stand-in services and a recorded
queue — no database, no job runner.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from advisor.assessment import QuestionRoundTrigger
from kernel.outbox import EventName, OutboxEvent
from worker import dispatcher

OWNER = uuid.UUID("00000000-0000-0000-0000-000000000001")


class FakeAssessment:
    def __init__(self, round_id: uuid.UUID | None) -> None:
        self.round_id = round_id
        self.requests: list[tuple[uuid.UUID, QuestionRoundTrigger]] = []

    async def request_questions(
        self, owner_id: uuid.UUID, *, trigger: QuestionRoundTrigger
    ) -> uuid.UUID | None:
        self.requests.append((owner_id, trigger))
        return self.round_id


@pytest.fixture
def queued(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def enqueue(name: str, **kwargs: Any) -> None:
        calls.append({"name": name, **kwargs})

    monkeypatch.setattr(dispatcher, "enqueue", enqueue)
    return calls


def _deps(assessment: FakeAssessment) -> Any:
    return SimpleNamespace(assessment=assessment)


def _profile_updated(source: str) -> OutboxEvent:
    return OutboxEvent(
        name=str(EventName.PROFILE_UPDATED),
        owner_id=OWNER,
        payload={"source": source, "version": 3, "count": 12},
    )


@pytest.mark.parametrize("source", ["github", "jira", "resume"])
async def test_new_evidence_opens_a_question_round_and_queues_it(
    source: str, queued: list[dict[str, Any]]
) -> None:
    round_id = uuid.uuid4()
    assessment = FakeAssessment(round_id)

    await dispatcher._handle(_deps(assessment), _profile_updated(source))

    assert assessment.requests == [(OWNER, QuestionRoundTrigger.EVIDENCE)]
    assert queued == [
        {
            "name": "assessment.generate_questions",
            "owner_id": str(OWNER),
            "round_id": str(round_id),
        }
    ]


async def test_an_answer_does_not_open_a_second_round(queued: list[dict[str, Any]]) -> None:
    assessment = FakeAssessment(uuid.uuid4())

    await dispatcher._handle(_deps(assessment), _profile_updated("self_reported"))

    assert assessment.requests == [] and queued == []


async def test_nothing_is_queued_when_there_is_nothing_to_ask(
    queued: list[dict[str, Any]],
) -> None:
    assessment = FakeAssessment(None)

    await dispatcher._handle(_deps(assessment), _profile_updated("github"))

    assert len(assessment.requests) == 1 and queued == []


# --- role maps waiting on an analysis (ADR 0018) ---------------------------


class FakeActivity:
    def __init__(self, *, released: Any = None, requested: Any = None) -> None:
        self.released = released
        self.requested = requested
        self.releases: list[uuid.UUID] = []
        self.requests: list[uuid.UUID] = []

    async def release_waiting_builds(self, owner_id: uuid.UUID) -> Any:
        self.releases.append(owner_id)
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


@pytest.mark.parametrize("status", ["ready", "failed"])
async def test_a_finished_analysis_starts_the_role_map_that_waited_for_it(
    status: str, queued: list[dict[str, Any]]
) -> None:
    build_id = uuid.uuid4()
    activity = FakeActivity(released=SimpleNamespace(id=build_id))

    await dispatcher._handle(_container(activity=activity), _analysis_finished(status))

    assert activity.releases == [OWNER]
    assert queued == [
        {"name": "rolemap.recluster", "owner_id": str(OWNER), "build_id": str(build_id)}
    ]


async def test_a_finished_analysis_queues_nothing_when_no_role_map_waited(
    queued: list[dict[str, Any]],
) -> None:
    activity = FakeActivity(released=None)

    await dispatcher._handle(_container(activity=activity), _analysis_finished("ready"))

    assert activity.releases == [OWNER] and queued == []


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


async def test_a_new_role_count_is_rebuilt_by_its_route_not_again_here(
    queued: list[dict[str, Any]],
) -> None:
    event = OutboxEvent(
        name=str(EventName.ROLE_COUNT_CHANGED),
        owner_id=OWNER,
        payload={"previous": 10, "current": 12},
    )

    await dispatcher._handle(_container(), event)

    assert queued == []
