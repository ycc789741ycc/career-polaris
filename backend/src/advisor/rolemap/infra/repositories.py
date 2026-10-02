"""SQLAlchemy implementations of the role map's repositories.

The six methods come from ``kernel.db.repository.SqlAlchemyRepository``. Every
role-map table is owner-zone, so every repository here is bound to one owner.
Members and requirements have no creation time stored, so they sort by id.
"""

from __future__ import annotations

import uuid
from typing import ClassVar

from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.elements import ColumnElement

from advisor.rolemap.domain import (
    BuildRun,
    BuildRunFilter,
    BuildRunRepository,
    CandidateStrength,
    CandidateStrengthFilter,
    CandidateStrengthRepository,
    LineageEntry,
    LineageEntryFilter,
    LineageEntryRepository,
    Role,
    RoleCandidate,
    RoleCandidateFilter,
    RoleCandidateRepository,
    RoleFilter,
    RoleFit,
    RoleFitFilter,
    RoleFitRepository,
    RoleMember,
    RoleMemberFilter,
    RoleMemberRepository,
    RoleRepository,
    RoleRequirement,
    RoleRequirementFilter,
    RoleRequirementRepository,
)
from advisor.rolemap.infra import mappers, models
from kernel.db.repository import SqlAlchemyRepository


class SqlAlchemyRoleRepository(SqlAlchemyRepository[Role, models.Role, RoleFilter], RoleRepository):
    model = models.Role
    id_column = models.Role.id
    created_column = models.Role.created_at
    owner_column: ClassVar[InstrumentedAttribute[uuid.UUID] | None] = models.Role.owner_id
    noun = "role"

    def to_entity(self, row: models.Role) -> Role:
        return mappers.role(row)

    def to_row(self, entity: Role) -> models.Role:
        return mappers.role_row(entity)

    def apply(self, row: models.Role, entity: Role) -> None:
        mappers.apply_role(row, entity)

    def id_of(self, entity: Role) -> uuid.UUID:
        return entity.id

    def conditions(self, filter: RoleFilter) -> list[ColumnElement[bool]]:
        found: list[ColumnElement[bool]] = []
        if filter.is_retired is True:
            found.append(models.Role.retired_at.is_not(None))
        if filter.is_retired is False:
            found.append(models.Role.retired_at.is_(None))
        if filter.origin is not None:
            found.append(models.Role.origin == str(filter.origin))
        return found


class SqlAlchemyRoleMemberRepository(
    SqlAlchemyRepository[RoleMember, models.RoleMember, RoleMemberFilter],
    RoleMemberRepository,
):
    model = models.RoleMember
    id_column = models.RoleMember.id
    created_column = models.RoleMember.id
    owner_column: ClassVar[InstrumentedAttribute[uuid.UUID] | None] = models.RoleMember.owner_id
    noun = "role member"

    def to_entity(self, row: models.RoleMember) -> RoleMember:
        return mappers.member(row)

    def to_row(self, entity: RoleMember) -> models.RoleMember:
        return mappers.member_row(entity)

    def apply(self, row: models.RoleMember, entity: RoleMember) -> None:
        mappers.apply_member(row, entity)

    def id_of(self, entity: RoleMember) -> uuid.UUID:
        return entity.id

    def conditions(self, filter: RoleMemberFilter) -> list[ColumnElement[bool]]:
        if filter.role_ids is None:
            return []
        return [models.RoleMember.role_id.in_(filter.role_ids)]


class SqlAlchemyRoleRequirementRepository(
    SqlAlchemyRepository[RoleRequirement, models.RoleRequirement, RoleRequirementFilter],
    RoleRequirementRepository,
):
    model = models.RoleRequirement
    id_column = models.RoleRequirement.id
    created_column = models.RoleRequirement.id
    owner_column: ClassVar[InstrumentedAttribute[uuid.UUID] | None] = (
        models.RoleRequirement.owner_id
    )
    noun = "role requirement"

    def to_entity(self, row: models.RoleRequirement) -> RoleRequirement:
        return mappers.requirement(row)

    def to_row(self, entity: RoleRequirement) -> models.RoleRequirement:
        return mappers.requirement_row(entity)

    def apply(self, row: models.RoleRequirement, entity: RoleRequirement) -> None:
        mappers.apply_requirement(row, entity)

    def id_of(self, entity: RoleRequirement) -> uuid.UUID:
        return entity.id

    def conditions(self, filter: RoleRequirementFilter) -> list[ColumnElement[bool]]:
        if filter.role_ids is None:
            return []
        return [models.RoleRequirement.role_id.in_(filter.role_ids)]


class SqlAlchemyLineageEntryRepository(
    SqlAlchemyRepository[LineageEntry, models.RoleLineage, LineageEntryFilter],
    LineageEntryRepository,
):
    model = models.RoleLineage
    id_column = models.RoleLineage.id
    created_column = models.RoleLineage.recorded_at
    owner_column: ClassVar[InstrumentedAttribute[uuid.UUID] | None] = models.RoleLineage.owner_id
    noun = "lineage entry"

    def to_entity(self, row: models.RoleLineage) -> LineageEntry:
        return mappers.lineage(row)

    def to_row(self, entity: LineageEntry) -> models.RoleLineage:
        return mappers.lineage_row(entity)

    def apply(self, row: models.RoleLineage, entity: LineageEntry) -> None:
        mappers.apply_lineage(row, entity)

    def id_of(self, entity: LineageEntry) -> uuid.UUID:
        return entity.id

    def conditions(self, filter: LineageEntryFilter) -> list[ColumnElement[bool]]:
        if filter.role_id is None:
            return []
        return [models.RoleLineage.role_id == filter.role_id]


class SqlAlchemyBuildRunRepository(
    SqlAlchemyRepository[BuildRun, models.BuildRun, BuildRunFilter],
    BuildRunRepository,
):
    model = models.BuildRun
    id_column = models.BuildRun.id
    created_column = models.BuildRun.requested_at
    owner_column: ClassVar[InstrumentedAttribute[uuid.UUID] | None] = models.BuildRun.owner_id
    noun = "role map build"

    def to_entity(self, row: models.BuildRun) -> BuildRun:
        return mappers.build_run(row)

    def to_row(self, entity: BuildRun) -> models.BuildRun:
        return mappers.build_run_row(entity)

    def apply(self, row: models.BuildRun, entity: BuildRun) -> None:
        mappers.apply_build_run(row, entity)

    def id_of(self, entity: BuildRun) -> uuid.UUID:
        return entity.id

    def conditions(self, filter: BuildRunFilter) -> list[ColumnElement[bool]]:
        if filter.statuses is None:
            return []
        return [models.BuildRun.status.in_([str(s) for s in filter.statuses])]


class SqlAlchemyRoleCandidateRepository(
    SqlAlchemyRepository[RoleCandidate, models.RoleCandidate, RoleCandidateFilter],
    RoleCandidateRepository,
):
    model = models.RoleCandidate
    id_column = models.RoleCandidate.id
    created_column = models.RoleCandidate.created_at
    owner_column: ClassVar[InstrumentedAttribute[uuid.UUID] | None] = models.RoleCandidate.owner_id
    noun = "role candidate"

    def to_entity(self, row: models.RoleCandidate) -> RoleCandidate:
        return mappers.candidate(row)

    def to_row(self, entity: RoleCandidate) -> models.RoleCandidate:
        return mappers.candidate_row(entity)

    def apply(self, row: models.RoleCandidate, entity: RoleCandidate) -> None:
        mappers.apply_candidate(row, entity)

    def id_of(self, entity: RoleCandidate) -> uuid.UUID:
        return entity.id

    def conditions(self, filter: RoleCandidateFilter) -> list[ColumnElement[bool]]:
        return []


class SqlAlchemyCandidateStrengthRepository(
    SqlAlchemyRepository[CandidateStrength, models.CandidateStrength, CandidateStrengthFilter],
    CandidateStrengthRepository,
):
    model = models.CandidateStrength
    id_column = models.CandidateStrength.id
    created_column = models.CandidateStrength.created_at
    owner_column: ClassVar[InstrumentedAttribute[uuid.UUID] | None] = (
        models.CandidateStrength.owner_id
    )
    noun = "candidate strength"

    def to_entity(self, row: models.CandidateStrength) -> CandidateStrength:
        return mappers.strength(row)

    def to_row(self, entity: CandidateStrength) -> models.CandidateStrength:
        return mappers.strength_row(entity)

    def apply(self, row: models.CandidateStrength, entity: CandidateStrength) -> None:
        mappers.apply_strength(row, entity)

    def id_of(self, entity: CandidateStrength) -> uuid.UUID:
        return entity.id

    def conditions(self, filter: CandidateStrengthFilter) -> list[ColumnElement[bool]]:
        return []


class SqlAlchemyRoleFitRepository(
    SqlAlchemyRepository[RoleFit, models.RoleFit, RoleFitFilter],
    RoleFitRepository,
):
    model = models.RoleFit
    id_column = models.RoleFit.id
    created_column = models.RoleFit.created_at
    owner_column: ClassVar[InstrumentedAttribute[uuid.UUID] | None] = models.RoleFit.owner_id
    noun = "fit"

    def to_entity(self, row: models.RoleFit) -> RoleFit:
        return mappers.fit(row)

    def to_row(self, entity: RoleFit) -> models.RoleFit:
        return mappers.fit_row(entity)

    def apply(self, row: models.RoleFit, entity: RoleFit) -> None:
        mappers.apply_fit(row, entity)

    def id_of(self, entity: RoleFit) -> uuid.UUID:
        return entity.id

    def conditions(self, filter: RoleFitFilter) -> list[ColumnElement[bool]]:
        fit = models.RoleFit
        found: list[ColumnElement[bool]] = []
        if filter.role_id is not None:
            found.append(fit.role_id == filter.role_id)
        if filter.assessment_id is not None:
            found.append(fit.assessment_id == filter.assessment_id)
        return found
