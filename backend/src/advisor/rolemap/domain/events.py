"""What the role map tells the rest of the system, as domain facts.

``advisor.rolemap.infra`` maps each to its outbox name and payload.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from advisor.rolemap.domain.identity import RoleLineage


@dataclass(frozen=True, slots=True)
class RoleRequirementsChanged:
    owner_id: uuid.UUID
    role_id: uuid.UUID
    requirements: int


@dataclass(frozen=True, slots=True)
class RoleSplitOrMerged:
    owner_id: uuid.UUID
    changes: tuple[RoleLineage, ...]


@dataclass(frozen=True, slots=True)
class RolesReclustered:
    owner_id: uuid.UUID
    roles: int


@dataclass(frozen=True, slots=True)
class CustomRoleAdded:
    """A role the user named. A company named with it goes to board discovery,
    with nothing about the user attached (domain decision 25)."""

    owner_id: uuid.UUID
    role_id: uuid.UUID
    company_name: str | None


@dataclass(frozen=True, slots=True)
class RoleMapBuildFinished:
    """A build closed, ``ready`` or ``failed``. The one trigger for scoring the
    fits, so each build is scored once, whatever it changed (ADR 0024)."""

    owner_id: uuid.UUID
    build_id: uuid.UUID
    status: str


@dataclass(frozen=True, slots=True)
class RoleCandidatesReplaced:
    """An analysis recommended a new set of roles. Their titles go to the
    market to be searched for, with nothing about the user attached
    (ADR 0025)."""

    owner_id: uuid.UUID
    titles: tuple[str, ...]


RoleMapEvent = (
    CustomRoleAdded
    | RoleCandidatesReplaced
    | RoleMapBuildFinished
    | RoleRequirementsChanged
    | RoleSplitOrMerged
    | RolesReclustered
)
