"""Role map's wire shapes: the bubble chart's roles and their fits, the
openings inside them, the candidates they come from, and what a rebuild
costs."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import date
from typing import Any, Literal

from advisor.rolemap import (
    FitView,
    MatchedPostingView,
    RoleCandidateView,
    RoleView,
)
from api.schemas.common import ApiModel, Page, Salary, Timestamp


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
    """One bubble. Its size is its fit (``GET /fits``), kept apart because it
    belongs to the User x Role pair."""

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
    """The most a role map can cost: a ceiling, not a prediction. ``cost_usd``
    includes scoring the fits once the build ends (ADR 0024)."""

    # A decimal string: money never goes through a float.
    cost_usd: str
    model_id: str | None
    max_roles: int
    fits_cost_usd: str
    # Null when there is nothing to price, so no model was asked.
    rate_is_published: bool | None = None


class RolePage(Page[Role]):
    pass


class RoleMapState(ApiModel):
    """How current the map on screen is (ADR 0027). It is built only when the
    user asks, so it says how old its market is, and whether the target
    locations changed since. Both are null before the first map."""

    # The oldest fetch among the sources its last build read.
    market_data_at: Timestamp | None
    # The target locations it was built for.
    built_for_locations: list[str] | None
    locations_changed: bool


class RoleCandidate(ApiModel):
    """A role the latest analysis recommended from the user's strengths, and
    what the last build made of it (ADR 0024)."""

    id: uuid.UUID
    # The analysis's order, best fit first.
    rank: int
    title: str
    description: str
    dimension_keys: list[str]
    # The role it became on the map; null when the user's target locations
    # had too few openings for it.
    role_id: uuid.UUID | None
    opening_count: int

    @classmethod
    def from_view(cls, candidate: RoleCandidateView) -> RoleCandidate:
        return cls(
            id=candidate.id,
            rank=candidate.rank,
            title=candidate.title,
            description=candidate.description,
            dimension_keys=list(candidate.dimension_keys),
            role_id=candidate.role_id,
            opening_count=candidate.opening_count,
        )


class RoleCandidatePage(Page[RoleCandidate]):
    pass


class FitGap(ApiModel):
    dimension_key: str
    user_score: int
    target_score: int
    delta: int


class UncoveredRequirement(ApiModel):
    statement: str
    weight: float


class Fit(ApiModel):
    """A bubble's size. Fit belongs to the User x Role pair, never to the role."""

    role_id: uuid.UUID
    score: int
    reasoning: str
    gaps: list[FitGap]
    # Requirements with no matching dimension: no evidence at all, which is
    # different from a low score.
    uncovered: list[UncoveredRequirement]
    model_id: str
    computed_at: Timestamp

    @classmethod
    def from_view(cls, f: FitView) -> Fit:
        return cls(
            role_id=f.role_id,
            score=f.score,
            reasoning=f.reasoning,
            # Stored as the JSON they were written as; validated on the way out.
            gaps=[FitGap.model_validate(g) for g in f.gaps],
            uncovered=[UncoveredRequirement.model_validate(u) for u in f.uncovered],
            model_id=f.model_id,
            computed_at=f.created_at,
        )


class MatchedPosting(ApiModel):
    """An opening inside one of the user's roles, with its own fit, worked
    out locally from its role's (Phase 8)."""

    posting_id: uuid.UUID
    role_id: uuid.UUID
    role_name: str
    title: str
    company_name: str
    location: str | None
    url: str | None
    salary: Salary | None
    # The opening's own fit (`posting`), or its role's before a build has
    # worked the opening's out (`role`).
    fit: int | None
    fit_basis: Literal["role", "posting"] = "role"
    # atsBoard, jsonLd or publicApi; never a site that forbids crawling.
    source_kind: str | None
    # The job site whose API found this opening, to be named beside its link
    # wherever the opening is shown (ADR 0025); null for an employer's board.
    credited_to: str | None
    # The day it was posted, as its source states it, else the day it was
    # first fetched.
    posted_on: date | None = None

    @classmethod
    def from_view(cls, m: MatchedPostingView) -> MatchedPosting:
        return cls(
            posting_id=m.posting_id,
            role_id=m.role_id,
            role_name=m.role_name,
            title=m.title,
            company_name=m.company_name,
            location=m.location,
            url=m.url,
            salary=Salary.of(m.salary),
            fit=m.fit,
            fit_basis=m.fit_basis,
            source_kind=m.source_kind,
            credited_to=m.credited_to,
            posted_on=m.posted_on,
        )


class FitPage(Page[Fit]):
    pass


class MatchedPostingPage(Page[MatchedPosting]):
    pass
