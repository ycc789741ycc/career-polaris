"""A role on one user's map: where it came from, the postings it was built
from, and the requirements read out of them.

Plain data with the rules that belong to it; ``advisor.rolemap.infra`` maps
these to and from the database.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from advisor.rolemap.domain.constants import MAX_COMPANY_NAME, MAX_ROLE_TITLE
from advisor.rolemap.domain.hiring_bar import HiringBar


class RoleOrigin(StrEnum):
    """Where a role came from (domain decision 25).

    ``recommended`` is one of the top k candidates from the latest analysis that
    the market has openings for (ADR 0024), retired by reconciliation when it
    falls out. ``custom`` is one the user added by
    title; it is never retired by reconciliation, does not count toward the
    k, and stays until the user removes it.
    """

    RECOMMENDED = "recommended"
    CUSTOM = "custom"


class CustomRoleError(ValueError):
    """A custom role the user cannot add as asked."""


@dataclass(slots=True)
class Role:
    """A cluster of postings in one user's target locations, or a role the
    user added themselves.

    ``id`` is stable across re-clustering: plans and fits point at it, so
    renumbering on every crawl would break them.
    """

    id: uuid.UUID
    owner_id: uuid.UUID
    name: str
    origin: RoleOrigin = RoleOrigin.RECOMMENDED
    # A custom role's company, if the user named one; its postings are searched
    # for at that company only.
    company_name: str | None = None
    # A custom role's private JD in market_user, if the user pasted one. It is
    # the role's requirement basis (domain decision 26).
    private_posting_id: uuid.UUID | None = None
    is_coherent: bool = True
    opening_count: int = 0
    hiring_bar: int = 50
    bar_confidence: float = 0.0
    bar_basis: str = "estimated"
    bar_sample_size: int = 0
    bar_reasoning: str | None = None
    salary_bands: dict[str, Any] = field(default_factory=dict)
    model_id: str | None = None
    template_version: str | None = None
    retired_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def custom(
        cls,
        *,
        owner_id: uuid.UUID,
        title: str,
        company_name: str | None,
        private_posting_id: uuid.UUID | None,
    ) -> Role:
        """A role the user named. Its title is theirs and stays theirs: an
        analysis reads its requirements but never renames it."""
        name = title.strip()
        if not name:
            raise CustomRoleError("a custom role needs a job title")
        if len(name) > MAX_ROLE_TITLE:
            raise CustomRoleError(f"a job title is at most {MAX_ROLE_TITLE} characters")
        company = (company_name or "").strip() or None
        if company is not None and len(company) > MAX_COMPANY_NAME:
            raise CustomRoleError(f"a company name is at most {MAX_COMPANY_NAME} characters")
        return cls(
            id=uuid.uuid4(),
            owner_id=owner_id,
            name=name,
            origin=RoleOrigin.CUSTOM,
            company_name=company,
            private_posting_id=private_posting_id,
        )

    @property
    def is_custom(self) -> bool:
        return self.origin is RoleOrigin.CUSTOM

    def refresh_market(self, *, opening_count: int, salary_bands: dict[str, Any]) -> None:
        """Keep an analysed role, refreshing only what needs no AI."""
        self.opening_count = opening_count
        self.salary_bands = salary_bands
        self.retired_at = None

    def analysed(
        self,
        *,
        name: str,
        is_coherent: bool,
        opening_count: int,
        bar: HiringBar,
        bar_reasoning: str,
        salary_bands: dict[str, Any],
        model_id: str,
        template_version: str,
    ) -> None:
        # A custom role keeps the title the user gave it.
        if not self.is_custom:
            self.name = name
        self.is_coherent = is_coherent
        self.opening_count = opening_count
        self.hiring_bar = bar.value
        self.bar_confidence = bar.confidence
        self.bar_basis = str(bar.basis)
        self.bar_sample_size = bar.sample_size
        self.bar_reasoning = bar_reasoning
        self.salary_bands = salary_bands
        self.model_id = model_id
        self.template_version = template_version
        self.retired_at = None

    def retire(self, at: datetime) -> None:
        self.retired_at = at


@dataclass(slots=True)
class RoleMember:
    """One posting a role was built from, by its shared posting id."""

    id: uuid.UUID
    owner_id: uuid.UUID
    role_id: uuid.UUID
    posting_key: str


@dataclass(slots=True)
class RoleRequirement:
    """Free text pulled from a role's postings. It has no dimension."""

    id: uuid.UUID
    owner_id: uuid.UUID
    role_id: uuid.UUID
    statement: str
    weight: float
    expected_level: str
