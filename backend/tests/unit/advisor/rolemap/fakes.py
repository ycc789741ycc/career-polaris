"""In-memory role-map storage, the domain's repository interfaces with no
database, and the market as the role map sees it."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from advisor.market import PostingView, SourcesRequestView, Visibility
from advisor.rolemap.domain import (
    BuildRun,
    BuildRunFilter,
    BuildRunRepository,
    CandidatePlacement,
    CandidatePlacementFilter,
    CandidatePlacementRepository,
    CandidateStrength,
    CandidateStrengthFilter,
    CandidateStrengthRepository,
    LineageEntry,
    LineageEntryFilter,
    LineageEntryRepository,
    OwnerRoleMap,
    PostingEvaluation,
    PostingEvaluationFilter,
    PostingEvaluationRepository,
    PostingFit,
    PostingFitFilter,
    PostingFitRepository,
    PostingRequirement,
    PostingRequirementFilter,
    PostingRequirementFit,
    PostingRequirementFitFilter,
    PostingRequirementFitRepository,
    PostingRequirementRepository,
    Role,
    RoleCandidate,
    RoleCandidateFilter,
    RoleCandidateRepository,
    RoleFilter,
    RoleFit,
    RoleFitFilter,
    RoleFitRepository,
    RoleMapEvent,
    RoleMapUnitOfWork,
    RoleMember,
    RoleMemberFilter,
    RoleMemberRepository,
    RoleRepository,
    RoleRequirement,
    RoleRequirementFilter,
    RoleRequirementRepository,
)
from kernel.errors import NotFoundError
from tests.unit.kernel.db.fake_repository import FakeRepository


@dataclass
class Store:
    roles: dict[uuid.UUID, Role] = field(default_factory=dict)
    members: dict[uuid.UUID, RoleMember] = field(default_factory=dict)
    requirements: dict[uuid.UUID, RoleRequirement] = field(default_factory=dict)
    lineage: dict[uuid.UUID, LineageEntry] = field(default_factory=dict)
    builds: dict[uuid.UUID, BuildRun] = field(default_factory=dict)
    placements: dict[uuid.UUID, CandidatePlacement] = field(default_factory=dict)
    candidates: dict[uuid.UUID, RoleCandidate] = field(default_factory=dict)
    strengths: dict[uuid.UUID, CandidateStrength] = field(default_factory=dict)
    fits: dict[uuid.UUID, RoleFit] = field(default_factory=dict)
    evaluations: dict[uuid.UUID, PostingEvaluation] = field(default_factory=dict)
    posting_requirements: dict[uuid.UUID, PostingRequirement] = field(default_factory=dict)
    posting_requirement_fits: dict[uuid.UUID, PostingRequirementFit] = field(default_factory=dict)
    posting_fits: dict[uuid.UUID, PostingFit] = field(default_factory=dict)
    events: list[RoleMapEvent] = field(default_factory=list)


class FakeRoles(FakeRepository[Role, RoleFilter], RoleRepository):
    owner_field = "owner_id"
    noun = "role"

    def matches(self, entity: Role, filter: RoleFilter) -> bool:
        return filter.is_retired is None or (entity.retired_at is not None) == filter.is_retired


class FakeMembers(FakeRepository[RoleMember, RoleMemberFilter], RoleMemberRepository):
    created_field = "id"
    updated_field = None
    owner_field = "owner_id"
    noun = "role member"

    def matches(self, entity: RoleMember, filter: RoleMemberFilter) -> bool:
        return filter.role_ids is None or entity.role_id in filter.role_ids


class FakeRequirements(
    FakeRepository[RoleRequirement, RoleRequirementFilter],
    RoleRequirementRepository,
):
    created_field = "id"
    updated_field = None
    owner_field = "owner_id"
    noun = "role requirement"

    def matches(self, entity: RoleRequirement, filter: RoleRequirementFilter) -> bool:
        return filter.role_ids is None or entity.role_id in filter.role_ids


class FakeLineage(FakeRepository[LineageEntry, LineageEntryFilter], LineageEntryRepository):
    created_field = "recorded_at"
    updated_field = None
    owner_field = "owner_id"
    noun = "lineage entry"

    def matches(self, entity: LineageEntry, filter: LineageEntryFilter) -> bool:
        return filter.role_id is None or entity.role_id == filter.role_id


class FakeBuilds(FakeRepository[BuildRun, BuildRunFilter], BuildRunRepository):
    created_field = "requested_at"
    updated_field = None
    owner_field = "owner_id"
    noun = "role map build"

    def matches(self, entity: BuildRun, filter: BuildRunFilter) -> bool:
        return filter.statuses is None or entity.status in filter.statuses


class FakePlacements(
    FakeRepository[CandidatePlacement, CandidatePlacementFilter], CandidatePlacementRepository
):
    updated_field = None
    owner_field = "owner_id"
    noun = "candidate placement"

    def matches(self, entity: CandidatePlacement, filter: CandidatePlacementFilter) -> bool:
        return (filter.build_run_id is None or entity.build_run_id == filter.build_run_id) and (
            filter.candidate_ids is None or entity.candidate_id in filter.candidate_ids
        )


class FakeCandidates(
    FakeRepository[RoleCandidate, RoleCandidateFilter],
    RoleCandidateRepository,
):
    updated_field = None
    owner_field = "owner_id"
    noun = "role candidate"

    def matches(self, entity: RoleCandidate, filter: RoleCandidateFilter) -> bool:
        return True


class FakeStrengths(
    FakeRepository[CandidateStrength, CandidateStrengthFilter],
    CandidateStrengthRepository,
):
    created_field = "dimension_key"
    updated_field = None
    owner_field = "owner_id"
    noun = "candidate strength"

    def matches(self, entity: CandidateStrength, filter: CandidateStrengthFilter) -> bool:
        return True


class FakeFits(FakeRepository[RoleFit, RoleFitFilter], RoleFitRepository):
    updated_field = None
    owner_field = "owner_id"
    noun = "fit"

    def matches(self, entity: RoleFit, filter: RoleFitFilter) -> bool:
        return (filter.role_id is None or entity.role_id == filter.role_id) and (
            filter.assessment_id is None or entity.assessment_id == filter.assessment_id
        )


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


class FakePostingRequirements(
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


class FakePostingRequirementFits(
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


class FakePostingFits(FakeRepository[PostingFit, PostingFitFilter], PostingFitRepository):
    updated_field = None
    owner_field = "owner_id"
    noun = "posting fit"

    def matches(self, entity: PostingFit, filter: PostingFitFilter) -> bool:
        return (filter.posting_keys is None or entity.posting_key in filter.posting_keys) and (
            filter.role_ids is None or entity.role_id in filter.role_ids
        )


class FakeOwner(OwnerRoleMap):
    def __init__(self, store: Store, owner_id: uuid.UUID) -> None:
        self.roles = FakeRoles(store.roles, owner_id=owner_id)
        self.members = FakeMembers(store.members, owner_id=owner_id)
        self.requirements = FakeRequirements(store.requirements, owner_id=owner_id)
        self.lineage = FakeLineage(store.lineage, owner_id=owner_id)
        self.builds = FakeBuilds(store.builds, owner_id=owner_id)
        self.placements = FakePlacements(store.placements, owner_id=owner_id)
        self.candidates = FakeCandidates(store.candidates, owner_id=owner_id)
        self.strengths = FakeStrengths(store.strengths, owner_id=owner_id)
        self.fits = FakeFits(store.fits, owner_id=owner_id)
        self.evaluations = FakeEvaluations(store.evaluations, owner_id=owner_id)
        self.posting_requirements = FakePostingRequirements(
            store.posting_requirements, owner_id=owner_id
        )
        self.posting_requirement_fits = FakePostingRequirementFits(
            store.posting_requirement_fits, owner_id=owner_id
        )
        self.posting_fits = FakePostingFits(store.posting_fits, owner_id=owner_id)
        self.pending: list[RoleMapEvent] = []

    def record(self, event: RoleMapEvent) -> None:
        self.pending.append(event)


class FakeRoleMapUnitOfWork(RoleMapUnitOfWork):
    def __init__(self, store: Store | None = None) -> None:
        self.store = store or Store()

    @asynccontextmanager
    async def for_owner(self, owner_id: uuid.UUID) -> AsyncIterator[FakeOwner]:
        scope = FakeOwner(self.store, owner_id)
        yield scope
        self.store.events.extend(scope.pending)


MARKET_AS_OF = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)


class FakeMarket:
    """The market as rolemap sees it. ``due`` are the sources a build has to
    wait for; ``fetched`` those the crawler has since fetched; ``searched``
    what each title's search found."""

    def __init__(
        self,
        postings: list[PostingView] | None = None,
        markets: list[str] | None = None,
        pasted: list[PostingView] | None = None,
        *,
        due: tuple[uuid.UUID, ...] = (),
        searched: dict[str, list[uuid.UUID]] | None = None,
    ) -> None:
        self.postings = postings or []
        self.chosen = markets or []
        self.pasted = {p.id: p for p in pasted or []}
        # Who pasted what, as row-level security keeps it: unset for postings
        # handed in up front, which every owner sees.
        self.pasted_by: dict[uuid.UUID, uuid.UUID] = {}
        self.needed = (uuid.uuid4(), *due)
        self.due = due
        self.fetched: set[uuid.UUID] = set()
        self.searched = searched or {}
        self.asked: list[dict[str, Any]] = []

    async def request_sources(self, **asked: Any) -> SourcesRequestView:
        self.asked.append(asked)
        return SourcesRequestView(needed=self.needed, due=self.due)

    async def pending_sources(self, source_ids: Any) -> tuple[uuid.UUID, ...]:
        return tuple(i for i in source_ids if i not in self.fetched)

    async def oldest_fetch(self, source_ids: Any) -> datetime | None:
        return MARKET_AS_OF if source_ids else None

    async def search_results(self, *, titles: Any, places: Any) -> dict[str, list[uuid.UUID]]:
        return {title: self.searched.get(title, []) for title in titles}

    async def has_searchable_place(self, owner_id: uuid.UUID) -> bool:
        return False

    def _is_theirs(self, owner_id: uuid.UUID, posting_id: uuid.UUID) -> bool:
        return self.pasted_by.get(posting_id, owner_id) == owner_id

    async def private_posting(self, owner_id: uuid.UUID, posting_id: uuid.UUID) -> PostingView:
        if posting_id not in self.pasted or not self._is_theirs(owner_id, posting_id):
            raise NotFoundError("job description not found")
        return self.pasted[posting_id]

    async def private_postings(self, owner_id: uuid.UUID) -> list[PostingView]:
        return [p for p in reversed(self.pasted.values()) if self._is_theirs(owner_id, p.id)]

    async def paste_job_description(
        self,
        owner_id: uuid.UUID,
        *,
        company_name: str,
        title: str,
        location: str | None,
        description: str,
    ) -> PostingView:
        pasted = PostingView(
            id=uuid.uuid4(),
            company_name=company_name,
            title=title,
            location=location,
            url=None,
            description=description,
            visibility=Visibility.PRIVATE,
            salary=None,
        )
        self.pasted[pasted.id] = pasted
        self.pasted_by[pasted.id] = owner_id
        return pasted

    async def delete_private_posting(self, owner_id: uuid.UUID, posting_id: uuid.UUID) -> None:
        self.pasted.pop(posting_id, None)

    async def target_locations(self, owner_id: uuid.UUID) -> list[str]:
        return self.chosen

    async def postings_in_scope(self, owner_id: uuid.UUID) -> list[PostingView]:
        return self.postings

    async def scope_with_vectors(
        self, owner_id: uuid.UUID, model_name: str
    ) -> list[tuple[str, PostingView, list[float] | None]]:
        # None: nothing embedded yet, so the service embeds them itself.
        return [(str(p.id), p, None) for p in self.postings]
