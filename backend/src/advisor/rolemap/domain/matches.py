"""Ordering the openings inside a user's roles.

Pure: the caller supplies each posting's role, the fit it is ranked by, and
the day it was posted. No AI runs here. The role map lists one role's openings
newest first ("Openings for this role", ADR 0049); the Advisor ranks them by
fit.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from advisor.rolemap.domain.constants import DEFAULT_MATCHES, MAX_MATCHES, MIN_MATCHES


@dataclass(frozen=True, slots=True)
class MatchCandidate:
    posting_id: str
    role_id: str
    role_name: str
    company_name: str
    title: str
    fit: int | None
    posted_on: date | None = None


class MatchOrder(StrEnum):
    """How a list of openings is ordered."""

    # Highest fit first, unscored last: the Advisor's openings.
    FIT = "fit"
    # Most recently posted first, undated last: the role map's.
    NEWEST = "newest"


def rank_matches(
    candidates: Iterable[MatchCandidate],
    *,
    limit: int | None = DEFAULT_MATCHES,
    one_per_company: bool = False,
    order: MatchOrder = MatchOrder.FIT,
) -> list[MatchCandidate]:
    """The first ``limit`` openings in ``order``, or all of them when
    ``limit`` is None: by fit, highest first and unscored last, or newest
    first and undated last.

    Ties are broken by role, company, then title, so the same inputs always
    give the same list. With ``one_per_company``, only each company's
    first-ranked opening is kept, before the limit, so the list fills from
    other companies rather than repeating one.
    """
    if limit is not None and not MIN_MATCHES <= limit <= MAX_MATCHES:
        raise ValueError(f"limit must be between {MIN_MATCHES} and {MAX_MATCHES}, got {limit}")

    def tie_break(c: MatchCandidate) -> tuple[str, str, str, str]:
        return (c.role_name.lower(), c.company_name.lower(), c.title.lower(), c.posting_id)

    if order is MatchOrder.NEWEST:
        ranked = sorted(
            candidates,
            key=lambda c: (
                c.posted_on is None,
                -(c.posted_on.toordinal() if c.posted_on else 0),
                *tie_break(c),
            ),
        )
    else:
        ranked = sorted(
            candidates,
            key=lambda c: (c.fit is None, -(c.fit or 0), *tie_break(c)),
        )
    if one_per_company:
        seen: set[str] = set()
        distinct: list[MatchCandidate] = []
        for candidate in ranked:
            company = candidate.company_name.strip().lower()
            if company in seen:
                continue
            seen.add(company)
            distinct.append(candidate)
        ranked = distinct
    return ranked[:limit]
