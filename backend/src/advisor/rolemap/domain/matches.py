"""Ranking the openings inside a user's roles (the prototype's "Top matched").

Pure: the caller supplies each posting's role and that role's current fit. No
AI runs here, so the rank is the role's fit — a posting's own requirements do
not move it yet — and the list says so.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

MIN_MATCHES = 1
MAX_MATCHES = 50
DEFAULT_MATCHES = 10


@dataclass(frozen=True, slots=True)
class MatchCandidate:
    posting_id: str
    role_id: str
    role_name: str
    company_name: str
    title: str
    fit: int | None


def rank_matches(
    candidates: Iterable[MatchCandidate],
    *,
    limit: int | None = DEFAULT_MATCHES,
    one_per_company: bool = False,
) -> list[MatchCandidate]:
    """The ``limit`` best openings, or all of them ranked when ``limit`` is
    None: highest role fit first, unscored last.

    Ties are broken by role, company, then title, so the same inputs always
    give the same list. With ``one_per_company``, only each company's
    best-ranked opening is kept, before the limit, so the list fills from
    other companies rather than repeating one.
    """
    if limit is not None and not MIN_MATCHES <= limit <= MAX_MATCHES:
        raise ValueError(f"limit must be between {MIN_MATCHES} and {MAX_MATCHES}, got {limit}")
    ranked = sorted(
        candidates,
        key=lambda c: (
            c.fit is None,
            -(c.fit or 0),
            c.role_name.lower(),
            c.company_name.lower(),
            c.title.lower(),
            c.posting_id,
        ),
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
