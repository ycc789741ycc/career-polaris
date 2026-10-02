"""How the role map's use cases reach stored data: interfaces in domain terms.

Every repository has the same six methods (ADR 0011): ``create``, ``get``,
``get_list`` (newest first, paged), ``get_count``, ``update`` and ``delete``,
over one frozen filter per aggregate whose unset fields do not filter.

Role members and requirements have no creation time stored, so their lists
come back in id order; callers that present them choose their own order.

All role-map data is owner-zone, so the unit of work has one scope: one user's
data, in one transaction. Events recorded in it are committed with it.
"""

from __future__ import annotations

import uuid
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Protocol

from advisor.rolemap.domain.build_run import BuildRun, BuildRunStatus, CandidatePlacement
from advisor.rolemap.domain.candidate import CandidateStrength, RoleCandidate
from advisor.rolemap.domain.events import RoleMapEvent
from advisor.rolemap.domain.fit import PostingFit, PostingRequirementFit, RoleFit
from advisor.rolemap.domain.lineage import LineageEntry
from advisor.rolemap.domain.own_posting import PostingEvaluation, PostingRequirement
from advisor.rolemap.domain.role import Role, RoleMember, RoleRequirement


class Repository[Entity, Filter](Protocol):
    """The six methods, as every role-map repository has them."""

    async def create(self, entity: Entity) -> Entity: ...

    async def get(self, entity_id: uuid.UUID) -> Entity | None: ...

    async def get_list(
        self, filter: Filter, page: int = 1, page_size: int | None = None
    ) -> list[Entity]: ...

    async def get_count(self, filter: Filter) -> int: ...

    async def update(self, entity: Entity) -> Entity: ...

    async def delete(self, entity_id: uuid.UUID) -> None: ...


@dataclass(frozen=True, slots=True)
class RoleFilter:
    is_retired: bool | None = None


class RoleRepository(Repository[Role, RoleFilter], Protocol): ...


@dataclass(frozen=True, slots=True)
class RoleMemberFilter:
    role_ids: tuple[uuid.UUID, ...] | None = None


class RoleMemberRepository(Repository[RoleMember, RoleMemberFilter], Protocol): ...


@dataclass(frozen=True, slots=True)
class RoleRequirementFilter:
    role_ids: tuple[uuid.UUID, ...] | None = None


class RoleRequirementRepository(Repository[RoleRequirement, RoleRequirementFilter], Protocol): ...


@dataclass(frozen=True, slots=True)
class LineageEntryFilter:
    role_id: uuid.UUID | None = None


class LineageEntryRepository(Repository[LineageEntry, LineageEntryFilter], Protocol): ...


@dataclass(frozen=True, slots=True)
class BuildRunFilter:
    statuses: tuple[BuildRunStatus, ...] | None = None


class BuildRunRepository(Repository[BuildRun, BuildRunFilter], Protocol): ...


@dataclass(frozen=True, slots=True)
class CandidatePlacementFilter:
    build_run_id: uuid.UUID | None = None
    candidate_ids: tuple[uuid.UUID, ...] | None = None


class CandidatePlacementRepository(
    Repository[CandidatePlacement, CandidatePlacementFilter], Protocol
): ...


@dataclass(frozen=True, slots=True)
class RoleCandidateFilter:
    """Nothing to filter on: a user has one set, the latest analysis's."""


class RoleCandidateRepository(Repository[RoleCandidate, RoleCandidateFilter], Protocol): ...


@dataclass(frozen=True, slots=True)
class CandidateStrengthFilter:
    """Nothing to filter on: a user has one set, beside their candidates."""


class CandidateStrengthRepository(
    Repository[CandidateStrength, CandidateStrengthFilter], Protocol
): ...


@dataclass(frozen=True, slots=True)
class RoleFitFilter:
    role_id: uuid.UUID | None = None
    assessment_id: uuid.UUID | None = None


class RoleFitRepository(Repository[RoleFit, RoleFitFilter], Protocol): ...


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
class PostingFitFilter:
    posting_keys: tuple[str, ...] | None = None


class PostingFitRepository(Repository[PostingFit, PostingFitFilter], Protocol): ...


class OwnerRoleMap(Protocol):
    roles: RoleRepository
    members: RoleMemberRepository
    requirements: RoleRequirementRepository
    lineage: LineageEntryRepository
    builds: BuildRunRepository
    placements: CandidatePlacementRepository
    candidates: RoleCandidateRepository
    strengths: CandidateStrengthRepository
    fits: RoleFitRepository
    evaluations: PostingEvaluationRepository
    posting_requirements: PostingRequirementRepository
    posting_requirement_fits: PostingRequirementFitRepository
    posting_fits: PostingFitRepository

    def record(self, event: RoleMapEvent) -> None: ...


class RoleMapUnitOfWork(Protocol):
    def for_owner(self, owner_id: uuid.UUID) -> AbstractAsyncContextManager[OwnerRoleMap]: ...
