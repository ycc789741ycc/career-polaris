"""Which recommended candidates become roles, and how many there can be.

The analysis recommends up to ``ROLE_CANDIDATE_COUNT`` roles from the user's
strengths (ADR 0024, ADR 0029). A build has the market searched for each one,
and keeps the top k (``ROLE_MAP_TOP_K``) that read most like the user's
strengths among those with at least ``MIN_POSTINGS_FOR_A_ROLE`` openings
(ADR 0027). Every kept role costs three calls on the user's key (naming,
difficulty, fit), so k bounds what a build can spend. Both numbers are
settings, passed in here as ``limit`` and ``ceiling``.

Everything here is local and free: embeddings compared by cosine, plus the
title-word rule custom roles use.

* A posting a candidate's own search found belongs to that candidate, if it is
  relevant to it; one a search found for no candidate it is relevant to is
  left out. A posting no search found (a company board's) goes to the nearest
  candidate, as before.
* Each posting goes to one candidate at most, so the kept roles never share an
  opening, and ``max_role_count`` stays a true ceiling for the cost the api
  shows before any embedding runs.
* ``fit_estimates`` ranks the candidates the market has against the user's
  dimensions, so the k chosen are the ones most like the user's strengths,
  not merely the first k the analysis listed.
"""

from __future__ import annotations

from collections.abc import Sequence

from advisor.rolemap.domain.constants import (
    CANDIDATE_MATCH_THRESHOLD,
    MIN_POSTINGS_FOR_A_ROLE,
    UNCITED_DIMENSION_WEIGHT,
)
from advisor.rolemap.domain.similarity import get_centroid, get_similarity_matrix

Vector = Sequence[float]


def max_role_count(posting_count: int, *, ceiling: int) -> int:
    """The most recommended roles ``posting_count`` postings can turn into,
    when a build keeps at most ``ceiling`` of them."""
    if posting_count < 0:
        raise ValueError("posting_count cannot be negative")
    if ceiling < 0:
        raise ValueError("ceiling cannot be negative")
    return min(posting_count // MIN_POSTINGS_FOR_A_ROLE, ceiling)


def assign_postings(
    candidates: Sequence[Vector],
    postings: Sequence[Vector],
    title_hits: Sequence[frozenset[int]],
    *,
    searched_by: Sequence[frozenset[int]] | None = None,
    threshold: float = CANDIDATE_MATCH_THRESHOLD,
) -> list[int | None]:
    """The candidate each posting is an opening for, or ``None``.

    ``title_hits[j]`` holds the candidates whose every title word posting ``j``
    names; ``searched_by[j]`` the candidates whose own search found it.

    * A posting a search found goes to the nearest of the candidates that
      searched for it and that it is relevant to: it names their title, or is
      at least ``threshold`` similar. If it is relevant to none of them it is
      left out, not handed to another candidate: a search matches its query
      against the whole description, so some of what it returns isn't the job.
    * Any other posting that names a candidate's title goes to the nearest of
      those, whatever the cosine: the title is the strongest sign there is.
      Otherwise it goes to the nearest candidate at or above ``threshold``.

    Ties go to the better-ranked (earlier) candidate, so the same inputs always
    give the same roles.
    """
    if len(title_hits) != len(postings):
        raise ValueError("title_hits needs one entry per posting")
    found_by = searched_by if searched_by is not None else [frozenset()] * len(postings)
    if len(found_by) != len(postings):
        raise ValueError("searched_by needs one entry per posting")
    if not -1.0 <= threshold <= 1.0:
        raise ValueError("threshold is a cosine, between -1 and 1")
    for hits, searchers in zip(title_hits, found_by, strict=True):
        if any(c < 0 or c >= len(candidates) for c in (*hits, *searchers)):
            raise ValueError("a posting names a candidate that does not exist")
    similarity = get_similarity_matrix(postings, candidates)
    assigned: list[int | None] = []
    for cosines, hits, searchers in zip(similarity, title_hits, found_by, strict=True):
        if searchers:
            relevant = [c for c in sorted(searchers) if c in hits or cosines[c] >= threshold]
            assigned.append(_nearest(cosines, relevant, floor=-1.0))
            continue
        pool = sorted(hits) if hits else list(range(len(candidates)))
        assigned.append(_nearest(cosines, pool, floor=-1.0 if hits else threshold))
    return assigned


def _nearest(cosines: Sequence[float], pool: Sequence[int], *, floor: float) -> int | None:
    """The candidate in ``pool`` a posting is most like, by its ``cosines``
    with every candidate; the first of equals."""
    best: int | None = None
    best_score = floor
    for candidate in pool:
        score = cosines[candidate]
        if score > best_score or (best is None and score >= floor):
            best, best_score = candidate, score
    return best


def fit_estimates(
    dimensions: Sequence[Vector],
    weights: Sequence[float],
    roles: Sequence[Sequence[Vector]],
    cited: Sequence[frozenset[int]],
    *,
    uncited_weight: float = UNCITED_DIMENSION_WEIGHT,
) -> list[float]:
    """How much each role's openings read like the user's strongest
    dimensions, relative to the other roles (ADR 0027). Free: local vectors.

    ``dimensions[d]`` embeds a dimension's name and the analysis's read of it;
    ``weights[d]`` is its score times confidence. ``roles[r]`` holds role
    ``r``'s openings' vectors, and ``cited[r]`` the dimensions its candidate
    rests on, which count fully; the rest count ``uncited_weight`` as much.

    Each role is its openings' centroid. A dimension's similarity to it is
    centred on that dimension's mean over every role, so a broad dimension
    that resembles every role lifts none of them. The estimate is the weighted
    mean of the centred similarities: higher is closer to the user's strengths.
    It says nothing about what a role needs that the user lacks.
    """
    if len(weights) != len(dimensions):
        raise ValueError("weights needs one entry per dimension")
    if len(cited) != len(roles):
        raise ValueError("cited needs one entry per role")
    if not roles:
        return []
    if not dimensions or not any(w > 0 for w in weights):
        return [0.0] * len(roles)
    for openings in roles:
        if not openings:
            raise ValueError("a role needs at least one opening for its centroid")
    centroids = [get_centroid(openings) for openings in roles]
    raw = get_similarity_matrix(dimensions, centroids)
    means = [sum(row) / len(row) for row in raw]
    estimates: list[float] = []
    for r in range(len(roles)):
        total = 0.0
        weight_sum = 0.0
        for d, weight in enumerate(weights):
            w = weight * (1.0 if d in cited[r] else uncited_weight)
            total += w * (raw[d][r] - means[d])
            weight_sum += w
        estimates.append(total / weight_sum if weight_sum else 0.0)
    return estimates


def choose_by_estimate(
    estimates: Sequence[float], eligible: Sequence[int], *, limit: int
) -> list[int]:
    """The ``limit`` eligible candidates with the best estimate, best first;
    the analysis's order (the lower index) breaks a tie."""
    if limit < 0:
        raise ValueError("limit cannot be negative")
    return sorted(eligible, key=lambda index: (-estimates[index], index))[:limit]


def keep_on_market(
    opening_counts: Sequence[int],
    *,
    limit: int | None = None,
    minimum: int = MIN_POSTINGS_FOR_A_ROLE,
) -> list[int]:
    """The candidates the market has: those with at least ``minimum``
    openings, in the analysis's order, at most ``limit`` of them (all, when
    ``limit`` is None)."""
    if limit is not None and limit < 0:
        raise ValueError("limit cannot be negative")
    if minimum < 1:
        raise ValueError("a role needs at least one opening")
    return [index for index, count in enumerate(opening_counts) if count >= minimum][:limit]
