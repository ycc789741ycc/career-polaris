"""How Target's use cases reach stored data: interfaces in domain terms.

Every repository has the same six methods (ADR 0011): ``create``, ``get``,
``get_list`` (newest first, paged), ``get_count``, ``update`` and ``delete``,
over one frozen filter per aggregate whose unset fields do not filter.
Requirements have no creation time stored, so they list by id; the use cases
order them by weight.

Everything stored is a posting of the user's own and what was made of it, all
owner-zone, so the unit of work has one scope: one user's data, in one
transaction.
"""

from __future__ import annotations

import uuid
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Protocol

from advisor.target.domain.own_posting import PostingEvaluation, PrivateJobPosting
from advisor.target.domain.posting_fit import (
    OwnPostingFit,
    PostingRequirement,
    PostingRequirementFit,
)


class Repository[Entity, Filter](Protocol):
    """The six methods, as every Target repository has them."""

    async def create(self, entity: Entity) -> Entity: ...

    async def get(self, entity_id: uuid.UUID) -> Entity | None: ...

    async def get_list(
        self, filter: Filter, page: int = 1, page_size: int | None = None
    ) -> list[Entity]: ...

    async def get_count(self, filter: Filter) -> int: ...

    async def update(self, entity: Entity) -> Entity: ...

    async def delete(self, entity_id: uuid.UUID) -> None: ...


@dataclass(frozen=True, slots=True)
class PrivateJobPostingFilter:
    """Every posting of the user's own; nothing narrows it yet."""


class PrivateJobPostingRepository(
    Repository[PrivateJobPosting, PrivateJobPostingFilter], Protocol
): ...


@dataclass(frozen=True, slots=True)
class PostingEvaluationFilter:
    private_job_posting_id: uuid.UUID | None = None


class PostingEvaluationRepository(
    Repository[PostingEvaluation, PostingEvaluationFilter], Protocol
): ...


@dataclass(frozen=True, slots=True)
class PostingRequirementFilter:
    private_job_posting_id: uuid.UUID | None = None


class PostingRequirementRepository(
    Repository[PostingRequirement, PostingRequirementFilter], Protocol
): ...


@dataclass(frozen=True, slots=True)
class PostingRequirementFitFilter:
    private_job_posting_id: uuid.UUID | None = None


class PostingRequirementFitRepository(
    Repository[PostingRequirementFit, PostingRequirementFitFilter], Protocol
): ...


@dataclass(frozen=True, slots=True)
class OwnPostingFitFilter:
    private_job_posting_ids: tuple[uuid.UUID, ...] | None = None


class OwnPostingFitRepository(Repository[OwnPostingFit, OwnPostingFitFilter], Protocol): ...


class OwnerTarget(Protocol):
    postings: PrivateJobPostingRepository
    evaluations: PostingEvaluationRepository
    requirements: PostingRequirementRepository
    requirement_fits: PostingRequirementFitRepository
    fits: OwnPostingFitRepository


class TargetUnitOfWork(Protocol):
    def for_owner(self, owner_id: uuid.UUID) -> AbstractAsyncContextManager[OwnerTarget]: ...
