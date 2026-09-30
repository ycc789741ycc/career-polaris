"""Which recommended candidates become roles, and how many there can be.

The analysis recommends up to ``CANDIDATE_ROLE_COUNT`` roles from the user's
strengths, best fit first (ADR 0024). A build searches the postings in the
user's target locations for each one, and keeps the first
``RECOMMENDED_ROLE_COUNT`` the market has at least ``MIN_POSTINGS_FOR_A_ROLE``
openings for. Every kept role costs two calls on the user's key, so the ten
bound what a build can spend.

Matching is local: embeddings compared by cosine, plus the title-word rule
custom roles use. Each posting goes to one candidate at most, so the ten
roles never share an opening, and ``max_role_count`` stays a true ceiling for
the cost the api shows before any embedding runs.
"""

from __future__ import annotations

from collections.abc import Sequence

# Below this, a candidate has no openings worth naming a role after.
MIN_POSTINGS_FOR_A_ROLE = 3
# How many recommended roles one role map analyses on the user's key: fixed by
# the system, so the cost is predictable (domain decision 23, ADR 0020). Roles
# the user adds themselves do not count toward it.
RECOMMENDED_ROLE_COUNT = 10
# How many candidates one analysis may recommend: twice the ten, so a candidate
# the market lacks leaves room for the next (ADR 0024).
CANDIDATE_ROLE_COUNT = 20
# The least cosine at which a posting counts as an opening for a candidate it
# does not name by title. Set for all-MiniLM-L6-v2 over a candidate's title and
# description against a posting's title and description.
CANDIDATE_MATCH_THRESHOLD = 0.40

Vector = Sequence[float]


def max_role_count(posting_count: int) -> int:
    """The most recommended roles ``posting_count`` postings can turn into."""
    if posting_count < 0:
        raise ValueError("posting_count cannot be negative")
    return min(posting_count // MIN_POSTINGS_FOR_A_ROLE, RECOMMENDED_ROLE_COUNT)


def assign_postings(
    candidates: Sequence[Vector],
    postings: Sequence[Vector],
    title_hits: Sequence[frozenset[int]],
    *,
    threshold: float = CANDIDATE_MATCH_THRESHOLD,
) -> list[int | None]:
    """The candidate each posting is an opening for, or ``None``.

    ``title_hits[j]`` holds the candidates whose every title word posting ``j``
    names. A posting that names any goes to the nearest of those, whatever the
    cosine: the title is the strongest sign there is. Otherwise it goes to the
    nearest candidate at or above ``threshold``. Ties go to the better-ranked
    (earlier) candidate, so the same inputs always give the same roles.
    """
    if len(title_hits) != len(postings):
        raise ValueError("title_hits needs one entry per posting")
    if not -1.0 <= threshold <= 1.0:
        raise ValueError("threshold is a cosine, between -1 and 1")
    assigned: list[int | None] = []
    for posting, hits in zip(postings, title_hits, strict=True):
        if any(c < 0 or c >= len(candidates) for c in hits):
            raise ValueError("title_hits names a candidate that does not exist")
        pool = sorted(hits) if hits else range(len(candidates))
        floor = -1.0 if hits else threshold
        best: int | None = None
        best_score = floor
        for candidate in pool:
            score = _cosine(candidates[candidate], posting)
            if score > best_score or (best is None and score >= floor):
                best, best_score = candidate, score
        assigned.append(best)
    return assigned


def keep_on_market(
    opening_counts: Sequence[int],
    *,
    limit: int = RECOMMENDED_ROLE_COUNT,
    minimum: int = MIN_POSTINGS_FOR_A_ROLE,
) -> list[int]:
    """The candidates that become roles: those with at least ``minimum``
    openings, in the analysis's order, at most ``limit`` of them."""
    if limit < 0:
        raise ValueError("limit cannot be negative")
    if minimum < 1:
        raise ValueError("a role needs at least one opening")
    return [index for index, count in enumerate(opening_counts) if count >= minimum][:limit]


def _cosine(left: Vector, right: Vector) -> float:
    if len(left) != len(right):
        raise ValueError("vectors must have the same length")
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    norms = sum(a * a for a in left) ** 0.5 * sum(b * b for b in right) ** 0.5
    return dot / norms if norms else 0.0
