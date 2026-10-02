"""Fit, gaps, and the requirements a person has no evidence for.

Fit is a relationship between a user and a role, never an attribute of the
role. Hiring bar and salary belong to the role; the bubble's size does not
(domain section 2.5).

A role's requirements and a user's dimensions live in different spaces, so the
mapping step is explicit. What a requirement maps to nothing means is the most
important output here.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

# How much an uncovered requirement costs, relative to a dimension scored zero
# against its target. A requirement with no evidence at all is worse than a low
# score, so it is not discounted.
_UNCOVERED_PENALTY = 1.0


@dataclass(frozen=True, slots=True)
class TargetScore:
    dimension_id: str
    target: int

    def __post_init__(self) -> None:
        if not 0 <= self.target <= 100:
            raise ValueError(f"target for {self.dimension_id} must be between 0 and 100")


@dataclass(frozen=True, slots=True)
class SkillGap:
    """The user's score minus the target on one dimension."""

    dimension_id: str
    user_score: int
    target_score: int

    @property
    def delta(self) -> int:
        return self.user_score - self.target_score

    @property
    def is_gap(self) -> bool:
        return self.delta < 0


@dataclass(frozen=True, slots=True)
class UncoveredRequirement:
    """A requirement matching none of the user's dimensions.

    That means no evidence at all, which is different from a low score, and it
    is never dropped silently — otherwise someone with narrow evidence would
    look like a strong fit.
    """

    statement: str
    weight: float


@dataclass(frozen=True, slots=True)
class FitResult:
    score: int
    gaps: tuple[SkillGap, ...]
    uncovered: tuple[UncoveredRequirement, ...]

    @property
    def largest_gaps(self) -> tuple[SkillGap, ...]:
        return tuple(sorted((g for g in self.gaps if g.is_gap), key=lambda g: g.delta))


def evaluate(
    *,
    user_scores: dict[str, int],
    targets: list[TargetScore],
    uncovered: list[UncoveredRequirement],
) -> FitResult:
    """Score one User x Role pair.

    Exceeding a target does not earn credit: being far past the bar on one axis
    does not compensate for being under it on another, which is how interview
    panels actually behave.
    """
    gaps = tuple(
        SkillGap(
            dimension_id=target.dimension_id,
            user_score=user_scores.get(target.dimension_id, 0),
            target_score=target.target,
        )
        for target in targets
    )

    if not gaps and not uncovered:
        return FitResult(score=0, gaps=(), uncovered=())

    shortfall = sum(max(0, -gap.delta) for gap in gaps)
    possible = sum(gap.target_score for gap in gaps)

    # Each uncovered requirement is weighted onto the same 0-100 scale so it
    # actually moves the number rather than being a footnote.
    uncovered_penalty = sum(100 * _UNCOVERED_PENALTY * r.weight for r in uncovered)
    uncovered_possible = sum(100 * r.weight for r in uncovered)

    denominator = possible + uncovered_possible
    if denominator == 0:
        return FitResult(score=100, gaps=gaps, uncovered=tuple(uncovered))

    ratio = (shortfall + uncovered_penalty) / denominator
    score = round(max(0.0, min(1.0, 1.0 - ratio)) * 100)
    return FitResult(score=score, gaps=gaps, uncovered=tuple(uncovered))


@dataclass(frozen=True, slots=True)
class ClosingLifts:
    """Fit points each gap is worth: what closing it alone would add."""

    by_dimension: dict[str, int]
    by_uncovered: tuple[int, ...]


def closing_lifts(
    *, gaps: Sequence[SkillGap], uncovered: Sequence[UncoveredRequirement]
) -> ClosingLifts:
    """Rank gaps by what they cost, with the same arithmetic as ``evaluate``.

    Closing one gap removes its share of the shortfall from the ratio, so it is
    worth ``100 * shortfall / denominator`` points. Gaps a user already clears
    are worth nothing and are left out. Rounding and the 0-100 clamp mean the
    lifts need not sum exactly to the distance from 100.
    """
    possible = sum(gap.target_score for gap in gaps)
    uncovered_possible = sum(100 * r.weight for r in uncovered)
    denominator = possible + uncovered_possible
    if denominator == 0:
        return ClosingLifts(by_dimension={}, by_uncovered=tuple(0 for _ in uncovered))
    return ClosingLifts(
        by_dimension={
            gap.dimension_id: round(100 * -gap.delta / denominator) for gap in gaps if gap.is_gap
        },
        by_uncovered=tuple(
            round(100 * 100 * _UNCOVERED_PENALTY * r.weight / denominator) for r in uncovered
        ),
    )


@dataclass(slots=True)
class RoleFit:
    """Fit between this user and one of their roles (ADR 0028).

    Fit lives on the User x Role pair, never on the role: a snapshot taken
    against the scores of one analysis (``assessment_id``), kept with what it
    was projected from so it can be re-read without the role.
    """

    id: uuid.UUID
    owner_id: uuid.UUID
    assessment_id: uuid.UUID
    role_id: uuid.UUID
    score: int
    reasoning: str
    target_profile: dict[str, int]
    gaps: tuple[dict[str, Any], ...]
    uncovered: tuple[dict[str, Any], ...]
    model_id: str
    template_version: str
    requirements: tuple[dict[str, Any], ...] = ()
    requirement_map: dict[str, str | None] = field(default_factory=dict)
    # What it read (``get_requirements_digest``): with ``assessment_id``, what
    # decides whether scoring the role again would change anything. None for
    # fits taken before it was recorded, which are always scored again.
    requirements_digest: str | None = None
    created_at: datetime | None = None

    def is_current(self, *, assessment_id: uuid.UUID, requirements_digest: str) -> bool:
        """Whether this fit read the same requirements and the same analysis's
        scores: scoring the role again would come out the same."""
        return (
            self.assessment_id == assessment_id
            and self.requirements_digest is not None
            and self.requirements_digest == requirements_digest
        )


@dataclass(slots=True)
class PostingRequirementFit:
    """The AI's evaluation of a posting of the user's own (Phase 8): its JD's
    requirements mapped onto the user's dimensions, with a target for each.

    The same projection a ``RoleFit`` makes, over one pasted JD's requirements
    instead of a role's. It is what a ``PostingFit`` is worked out from, so it
    keeps everything that needs: the requirements, the mapping, the targets.
    """

    id: uuid.UUID
    owner_id: uuid.UUID
    private_job_posting_id: uuid.UUID
    assessment_id: uuid.UUID
    requirements: tuple[dict[str, Any], ...]
    requirement_map: dict[str, str | None]
    target_profile: dict[str, int]
    reasoning: str
    model_id: str
    template_version: str
    # What it read, as on a ``RoleFit``.
    requirements_digest: str | None = None
    created_at: datetime | None = None

    def is_current(self, *, assessment_id: uuid.UUID, requirements_digest: str) -> bool:
        """Whether rescoring would read the same requirements and the same
        analysis's scores, and so come out the same."""
        return (
            self.assessment_id == assessment_id
            and self.requirements_digest is not None
            and self.requirements_digest == requirements_digest
        )


class PostingFitBasis(StrEnum):
    """Which AI fit a ``PostingFit`` was worked out from."""

    # A posting of the user's own: its ``PostingRequirementFit``.
    OWN = "own"


@dataclass(slots=True)
class PostingFit:
    """The user's fit to one posting, worked out locally from an AI fit. It is
    never an AI call (Phase 8).

    ``posting_key`` names the posting as ``rolemap.role_member`` does:
    ``private:<id>`` for a posting of the user's own. ``source_fit_id`` is the
    AI fit it came from, and ``assessment_id`` the analysis whose scores it
    was worked out against.
    """

    id: uuid.UUID
    owner_id: uuid.UUID
    posting_key: str
    basis: PostingFitBasis
    source_fit_id: uuid.UUID
    assessment_id: uuid.UUID
    score: int
    requirements: tuple[dict[str, Any], ...]
    requirement_map: dict[str, str | None]
    target_profile: dict[str, int]
    gaps: tuple[dict[str, Any], ...]
    uncovered: tuple[dict[str, Any], ...]
    created_at: datetime | None = None


def get_own_posting_key(private_job_posting_id: uuid.UUID) -> str:
    """The key a posting of the user's own is stored under."""
    return f"private:{private_job_posting_id}"


def get_posting_fit(
    *,
    requirements: Sequence[Mapping[str, Any]],
    requirement_map: Mapping[str, str | None],
    target_profile: Mapping[str, int],
    user_scores: Mapping[str, int],
) -> FitResult:
    """A posting's fit from an AI fit's mapping and targets: plain arithmetic.

    A requirement mapped to none of the user's dimensions is uncovered, at its
    weight; a target on a dimension the user does not have is dropped, as the
    projection's are. The score, gaps and uncovered requirements are then
    ``evaluate``'s.
    """
    targets = [
        TargetScore(dimension_id=key, target=target)
        for key, target in sorted(target_profile.items())
        if key in user_scores
    ]
    seen: set[str] = set()
    uncovered: list[UncoveredRequirement] = []
    for requirement in requirements:
        statement = str(requirement["statement"])
        if statement in seen:
            continue
        seen.add(statement)
        if requirement_map.get(statement) not in user_scores:
            uncovered.append(UncoveredRequirement(statement, float(requirement["weight"])))
    return evaluate(user_scores=dict(user_scores), targets=targets, uncovered=uncovered)


def get_requirements_digest(
    requirements: Sequence[Mapping[str, Any]], *, template_version: str
) -> str:
    """What an AI fit reads, as a hash: its requirements (statement, weight and
    expected level, in the order they are sent) and the fit prompt's version.

    Two fits with the same digest, taken against the same analysis's scores,
    come out the same, so the second need not be asked for. A new prompt
    version changes every digest, so it scores everything once.
    """
    payload = json.dumps(
        {
            "template": template_version,
            "requirements": [
                [str(r["statement"]), float(r["weight"]), str(r["expected_level"])]
                for r in requirements
            ],
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
