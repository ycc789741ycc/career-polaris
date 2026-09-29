"""What a gap plan or a résumé is aimed at (domain decision 26, ADR 0022).

A Target is one of the user's Roles — recommended or custom — and optionally
one opening in it, plus a frozen snapshot of what it requires and how the user
measured up when it was chosen. Postings expire and roles re-cluster; the
snapshot is what lets a plan still say what it was planned against.

Several features aim at Targets, so the concept has its own package rather
than living in any of them (ADR 0005).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class RequirementBasis(StrEnum):
    """Where the requirements came from, shown next to them. The most specific
    source a Target has wins."""

    # A custom role's private JD: the text the user pasted.
    POSTING = "posting"
    # The Role's requirements across its openings.
    ROLE = "role"


class TargetError(ValueError):
    """A Target that cannot be planned or written for."""


@dataclass(frozen=True, slots=True)
class TargetRef:
    """A Role, and optionally one opening in it."""

    role_id: str
    job_posting_id: str | None = None

    def __post_init__(self) -> None:
        if not self.role_id:
            raise TargetError("a target needs a role")
        if self.job_posting_id == "":
            raise TargetError("an opening needs an id")

    def to_dict(self) -> dict[str, str | None]:
        return {"role_id": self.role_id, "job_posting_id": self.job_posting_id}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TargetRef:
        return cls(str(data["role_id"]), data.get("job_posting_id"))


@dataclass(frozen=True, slots=True)
class Requirement:
    statement: str
    weight: float
    expected_level: str


@dataclass(frozen=True, slots=True)
class DimensionGap:
    """One of the user's dimensions against what the Target expects of it."""

    dimension_key: str
    name: str
    user_score: int
    target_score: int
    # Fit points closing this gap alone is worth.
    lift: int

    @property
    def delta(self) -> int:
        return self.user_score - self.target_score

    @property
    def key(self) -> str:
        return gap_key_for_dimension(self.dimension_key)


@dataclass(frozen=True, slots=True)
class UncoveredGap:
    """A requirement with no evidence at all behind it."""

    statement: str
    weight: float
    lift: int

    @property
    def key(self) -> str:
        return gap_key_for_uncovered(self.statement)


@dataclass(frozen=True, slots=True)
class TargetSnapshot:
    ref: TargetRef
    title: str
    company: str
    # The Role the Target is; kept by name too, since roles re-cluster.
    role_id: str
    role_name: str
    requirements: tuple[Requirement, ...]
    basis: RequirementBasis
    fit_score: int | None
    # Every dimension the Target touches, cleared or not.
    dimensions: tuple[DimensionGap, ...]
    uncovered: tuple[UncoveredGap, ...]
    # Requirement statement -> the user's dimension it maps to, or None.
    requirement_map: dict[str, str | None]
    taken_at: datetime

    def __post_init__(self) -> None:
        if not self.requirements:
            raise TargetError(
                "this role has no requirements to plan against yet; "
                "add its job description on the role map"
            )

    @property
    def label(self) -> str:
        return f"{self.role_name} · {self.company}" if self.company else self.role_name

    @property
    def open_gaps(self) -> tuple[DimensionGap | UncoveredGap, ...]:
        """What stands between the user and the Target, costliest first.

        Uncovered requirements come before a dimension gap of the same lift:
        having no evidence at all is worse than scoring low.
        """
        shortfalls = [d for d in self.dimensions if d.delta < 0]
        ranked: list[DimensionGap | UncoveredGap] = [*self.uncovered, *shortfalls]
        return tuple(sorted(ranked, key=lambda gap: (-gap.lift, isinstance(gap, DimensionGap))))

    def to_dict(self) -> dict[str, Any]:
        return {
            "ref": self.ref.to_dict(),
            "title": self.title,
            "company": self.company,
            "role_id": self.role_id,
            "role_name": self.role_name,
            "requirements": [
                {"statement": r.statement, "weight": r.weight, "expected_level": r.expected_level}
                for r in self.requirements
            ],
            "basis": str(self.basis),
            "fit_score": self.fit_score,
            "dimensions": [
                {
                    "dimension_key": d.dimension_key,
                    "name": d.name,
                    "user_score": d.user_score,
                    "target_score": d.target_score,
                    "lift": d.lift,
                }
                for d in self.dimensions
            ],
            "uncovered": [
                {"statement": u.statement, "weight": u.weight, "lift": u.lift}
                for u in self.uncovered
            ],
            "requirement_map": dict(self.requirement_map),
            "taken_at": self.taken_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TargetSnapshot:
        return cls(
            ref=TargetRef.from_dict(data["ref"]),
            title=data["title"],
            company=data["company"],
            role_id=str(data["role_id"]),
            role_name=data.get("role_name") or data["title"],
            requirements=tuple(Requirement(**r) for r in data["requirements"]),
            basis=RequirementBasis(data["basis"]),
            fit_score=data.get("fit_score"),
            dimensions=tuple(DimensionGap(**d) for d in data["dimensions"]),
            uncovered=tuple(UncoveredGap(**u) for u in data["uncovered"]),
            requirement_map=dict(data.get("requirement_map", {})),
            taken_at=datetime.fromisoformat(data["taken_at"]),
        )


def gap_key_for_dimension(dimension_key: str) -> str:
    return f"dim:{dimension_key}"


def gap_key_for_uncovered(statement: str) -> str:
    """Stable across plan versions, so completion can follow the same gap."""
    slug = re.sub(r"[^a-z0-9]+", "-", statement.casefold()).strip("-")
    return f"req:{slug[:80]}"
