"""In-memory Fill the gap storage: the domain's repository interfaces, with no
database."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from advisor.gapfill.domain import (
    GapFillEvent,
    GapFillUnitOfWork,
    GapQuestion,
    GapQuestionFilter,
    GapQuestionRepository,
    OwnerGapFill,
    QuestionSet,
    QuestionSetFilter,
    QuestionSetRepository,
)
from tests.unit.kernel.db.fake_repository import FakeRepository


@dataclass
class Store:
    sets: dict[uuid.UUID, QuestionSet] = field(default_factory=dict)
    questions: dict[uuid.UUID, GapQuestion] = field(default_factory=dict)
    events: list[GapFillEvent] = field(default_factory=list)


class FakeSets(FakeRepository[QuestionSet, QuestionSetFilter], QuestionSetRepository):
    updated_field = None
    owner_field = "owner_id"
    noun = "question set"

    def matches(self, entity: QuestionSet, filter: QuestionSetFilter) -> bool:
        if filter.role_id is not None and entity.role_id != filter.role_id:
            return False
        if filter.job_posting_id is not None and entity.job_posting_id != filter.job_posting_id:
            return False
        if filter.role_only and filter.job_posting_id is None and entity.job_posting_id:
            return False
        return filter.statuses is None or entity.status in filter.statuses


class FakeQuestions(FakeRepository[GapQuestion, GapQuestionFilter], GapQuestionRepository):
    created_field = "id"
    updated_field = None
    owner_field = "owner_id"
    noun = "question"

    def matches(self, entity: GapQuestion, filter: GapQuestionFilter) -> bool:
        return filter.set_ids is None or entity.set_id in filter.set_ids


class FakeOwner(OwnerGapFill):
    def __init__(self, store: Store, owner_id: uuid.UUID) -> None:
        self.sets = FakeSets(store.sets, owner_id=owner_id)
        self.questions = FakeQuestions(store.questions, owner_id=owner_id)
        self.pending: list[GapFillEvent] = []

    def record(self, event: GapFillEvent) -> None:
        self.pending.append(event)


class FakeGapFillUnitOfWork(GapFillUnitOfWork):
    def __init__(self, store: Store | None = None) -> None:
        self.store = store or Store()

    @asynccontextmanager
    async def for_owner(self, owner_id: uuid.UUID) -> AsyncIterator[FakeOwner]:
        scope = FakeOwner(self.store, owner_id)
        yield scope
        self.store.events.extend(scope.pending)
