"""A role on one user's map: the postings it groups, and the requirements read
out of them. The market's side only: nothing in it is about the user.

Plain data with the rules that belong to it; ``advisor.rolemap.infra`` maps
these to and from the database.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from advisor.rolemap.domain.hiring_bar import HiringBar

# Where or how a job is worked, and gender tags: never part of a role's name.
_WORK_TAG = (
    r"(?:fully\s+|100%\s+)?remote|hybrid|on[\s-]?site|in[\s-]office|worldwide|anywhere"
    r"|wfh|work\s+from\s+home|[mfwdx](?:\s*/\s*[mfwdx]){1,3}|all\s+genders"
)
# A trailing "(Remote)", "[m/f/x]", "(Remote, US)", " - Remote" or ", Hybrid".
_TRAILING_TAG = re.compile(
    rf"\s*(?:[(\[]\s*(?:{_WORK_TAG})(?:\s*[,/&|]\s*[^)\]]*)?\s*[)\]]"
    rf"|\s[-\u2013\u2014|:]\s*(?:{_WORK_TAG})|,\s*(?:{_WORK_TAG}))\s*$",
    re.IGNORECASE,
)


def parse_role_name(name: str) -> str:
    """A role's name as the map shows it, from the name a model gave it: one
    job title, with any trailing work-arrangement or gender tag taken off
    ("Senior Data Scientist (Remote)" is "Senior Data Scientist"). A name that
    is nothing but a tag is kept as it came."""
    cleaned = name.strip()
    while (stripped := _TRAILING_TAG.sub("", cleaned).strip()) != cleaned and stripped:
        cleaned = stripped
    return cleaned


@dataclass(slots=True)
class Role:
    """A group of openings in one user's target locations, found for one of
    the roles their analysis recommended, with what those openings ask for.
    How the user measures up to it is its ``RoleFit``, never the role's.

    ``id`` is stable across re-clustering: plans and fits point at it, so
    renumbering on every crawl would break them.
    """

    id: uuid.UUID
    owner_id: uuid.UUID
    name: str
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
        self.name = parse_role_name(name)
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
