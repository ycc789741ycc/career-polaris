"""In-memory Target storage: the domain's repository interfaces with no
database."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from advisor.target.domain import (
    OwnerTarget,
    OwnPostingFit,
    OwnPostingFitFilter,
    OwnPostingFitRepository,
    PostingEvaluation,
    PostingEvaluationFilter,
    PostingEvaluationRepository,
    PostingRequirement,
    PostingRequirementFilter,
    PostingRequirementFit,
    PostingRequirementFitFilter,
    PostingRequirementFitRepository,
    PostingRequirementRepository,
    PrivateJobPosting,
    PrivateJobPostingFilter,
    PrivateJobPostingRepository,
    TargetUnitOfWork,
)
from tests.unit.kernel.db.fake_repository import FakeRepository


@dataclass
class Store:
    postings: dict[uuid.UUID, PrivateJobPosting] = field(default_factory=dict)
    evaluations: dict[uuid.UUID, PostingEvaluation] = field(default_factory=dict)
    requirements: dict[uuid.UUID, PostingRequirement] = field(default_factory=dict)
    requirement_fits: dict[uuid.UUID, PostingRequirementFit] = field(default_factory=dict)
    fits: dict[uuid.UUID, OwnPostingFit] = field(default_factory=dict)


class FakePostings(
    FakeRepository[PrivateJobPosting, PrivateJobPostingFilter], PrivateJobPostingRepository
):
    updated_field = None
    owner_field = "owner_id"
    noun = "posting"

    def matches(self, entity: PrivateJobPosting, filter: PrivateJobPostingFilter) -> bool:
        return True


class FakeEvaluations(
    FakeRepository[PostingEvaluation, PostingEvaluationFilter], PostingEvaluationRepository
):
    created_field = "requested_at"
    updated_field = None
    owner_field = "owner_id"
    noun = "posting evaluation"

    def matches(self, entity: PostingEvaluation, filter: PostingEvaluationFilter) -> bool:
        return (
            filter.private_job_posting_id is None
            or entity.private_job_posting_id == filter.private_job_posting_id
        )


class FakeRequirements(
    FakeRepository[PostingRequirement, PostingRequirementFilter], PostingRequirementRepository
):
    created_field = "id"
    updated_field = None
    owner_field = "owner_id"
    noun = "posting requirement"

    def matches(self, entity: PostingRequirement, filter: PostingRequirementFilter) -> bool:
        return (
            filter.private_job_posting_id is None
            or entity.private_job_posting_id == filter.private_job_posting_id
        )


class FakeRequirementFits(
    FakeRepository[PostingRequirementFit, PostingRequirementFitFilter],
    PostingRequirementFitRepository,
):
    updated_field = None
    owner_field = "owner_id"
    noun = "posting requirement fit"

    def matches(self, entity: PostingRequirementFit, filter: PostingRequirementFitFilter) -> bool:
        return (
            filter.private_job_posting_id is None
            or entity.private_job_posting_id == filter.private_job_posting_id
        )


class FakeFits(FakeRepository[OwnPostingFit, OwnPostingFitFilter], OwnPostingFitRepository):
    updated_field = None
    owner_field = "owner_id"
    noun = "posting fit"

    def matches(self, entity: OwnPostingFit, filter: OwnPostingFitFilter) -> bool:
        return (
            filter.private_job_posting_ids is None
            or entity.private_job_posting_id in filter.private_job_posting_ids
        )


class FakeOwner(OwnerTarget):
    def __init__(self, store: Store, owner_id: uuid.UUID) -> None:
        self.postings = FakePostings(store.postings, owner_id=owner_id)
        self.evaluations = FakeEvaluations(store.evaluations, owner_id=owner_id)
        self.requirements = FakeRequirements(store.requirements, owner_id=owner_id)
        self.requirement_fits = FakeRequirementFits(store.requirement_fits, owner_id=owner_id)
        self.fits = FakeFits(store.fits, owner_id=owner_id)


class FakeTargetUnitOfWork(TargetUnitOfWork):
    def __init__(self, store: Store | None = None) -> None:
        self.store = store or Store()

    @asynccontextmanager
    async def for_owner(self, owner_id: uuid.UUID) -> AsyncIterator[FakeOwner]:
        yield FakeOwner(self.store, owner_id)


class FakeObjectStore:
    """Object storage in memory, keyed as the real one keys it."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(self, key: str, content: bytes, content_type: str) -> None:
        self.objects[key] = content

    def get(self, key: str) -> bytes:
        return self.objects[key]

    def delete(self, key: str) -> None:
        self.objects.pop(key, None)
