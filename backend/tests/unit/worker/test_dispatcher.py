"""The outbox dispatcher turning evidence changes into question rounds (ADR 0012).

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
