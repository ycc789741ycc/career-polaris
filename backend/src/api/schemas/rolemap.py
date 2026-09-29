"""Role map's wire shapes: the bubble chart's roles and what a rebuild costs."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import Field

from advisor.rolemap import MAX_COMPANY_NAME, MAX_ROLE_TITLE, RoleView
from api.schemas.common import ApiModel, Page, RequestModel


class SalaryBand(ApiModel):
    low: int
    mid: int
    high: int
    currency: str
    sample_size: int
    # A thin market shows a low-confidence band rather than hiding the role.
    is_confident: bool


class RoleRequirement(ApiModel):
    statement: str
    weight: float
    expected_level: str


class Role(ApiModel):
    """One bubble. Its size, the fit, is the assessment's (``GET /fits``)."""

    id: uuid.UUID
    name: str
    # X axis. `estimated` bubbles are drawn with a dashed outline, because no
    # real interview reports back them yet.
    hiring_bar: int
    bar_basis: str
    bar_confidence: float
    bar_reasoning: str | None
    opening_count: int
    # Y axis, one band per market the user selected; `all` when none is.
    salary_bands: dict[str, SalaryBand]
    is_coherent: bool
    requirements: list[RoleRequirement]
    # `recommended`, one of the ten, or `custom`: added by the user and drawn
    # as "yours" (ADR 0021).
    origin: Literal["recommended", "custom"]
    company_name: str | None
    # A custom role's private JD, when the user pasted one.
    private_posting_id: uuid.UUID | None

    @classmethod
    def from_view(cls, role: RoleView) -> Role:
        return cls(
            id=role.id,
            name=role.name,
            hiring_bar=role.hiring_bar,
            bar_basis=role.bar_basis,
            bar_confidence=role.bar_confidence,
            bar_reasoning=role.bar_reasoning,
            opening_count=role.opening_count,
            salary_bands=_bands(role.salary_bands),
            is_coherent=role.is_coherent,
            requirements=[
                RoleRequirement(
                    statement=r.statement, weight=r.weight, expected_level=r.expected_level
                )
                for r in role.requirements
            ],
            origin="custom" if role.is_custom else "recommended",
            company_name=role.company_name,
            private_posting_id=role.private_posting_id,
        )


def _bands(bands: Mapping[str, Any]) -> dict[str, SalaryBand]:
    # The role stores its bands as the JSON it was given; validating them here
    # is what turns a stored shape that drifted into a failure, not a blank.
    return {market: SalaryBand.model_validate(band) for market, band in bands.items()}


class RoleMapEstimate(ApiModel):
    """The most a role map can cost: a ceiling, not a prediction."""

    # A decimal string: money never goes through a float.
    cost_usd: str
    model_id: str | None
    max_clusters: int
    # Null when there is nothing to price, so no model was asked.
    rate_is_published: bool | None = None


class RolePage(Page[Role]):
    pass


class CustomRoleRequest(RequestModel):
    """A role of the user's own (domain decision 25): a title, and optionally a
    company and a job description, which stays private to the user."""

    title: str = Field(min_length=1, max_length=MAX_ROLE_TITLE)
    company_name: str | None = Field(default=None, max_length=MAX_COMPANY_NAME)
    job_description: str | None = Field(default=None, max_length=50_000)


class CustomRoleEstimate(ApiModel):
    """What adding a custom role will cost, shown before "Add to Role Map"."""

    cost_usd: str
    model_id: str | None
    # Open postings in scope the role takes in, by title (and company).
    matches: int
    rate_is_published: bool | None = None
