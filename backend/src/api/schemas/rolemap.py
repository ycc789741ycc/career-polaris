"""Role map's wire shapes: the bubble chart's roles and how many it analyses."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from pydantic import Field

from advisor.rolemap import MAX_ROLE_COUNT, MIN_ROLE_COUNT, RoleView
from api.schemas.common import ApiModel, RequestModel


class RoleMapSettings(RequestModel):
    """How many roles the role map analyses on the user's key (ADR 0003).

    Both the body of a change and the answer to a read, so it keeps a
    request's leniency.
    """

    role_count: int = Field(ge=MIN_ROLE_COUNT, le=MAX_ROLE_COUNT)


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
    # The k this estimate was priced for (ADR 0003).
    role_count: int
    # Null when there is nothing to price, so no model was asked.
    rate_is_published: bool | None = None
