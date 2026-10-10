"""How alike two sets of embeddings are: every cosine at once.

A build compares each posting in scope with each candidate, each candidate
role's centroid with each of the user's dimensions, and each opening with its
role's requirements. A scope runs to thousands of postings, so the cosines are
one matrix product rather than a loop in the interpreter. The result is plain
lists: nothing outside this module sees numpy.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

# Cosines are compared with one another and with thresholds, and a matrix
# product sums in another order than a loop would. Rounded here, two equal
# similarities stay equal, so a tie still goes to the better-ranked candidate.
_DECIMALS = 12


def get_similarity_matrix(
    left: Sequence[Sequence[float]], right: Sequence[Sequence[float]]
) -> list[list[float]]:
    """The cosine of each ``left`` vector with each ``right`` one:
    ``[i][j]`` compares ``left[i]`` with ``right[j]``. A zero vector is like
    nothing, 0."""
    widths = {len(vector) for vector in (*left, *right)}
    if len(widths) > 1:
        raise ValueError("vectors must have the same length")
    if not left or not right:
        return [[] for _ in left]
    a = np.asarray(left, dtype=np.float64)
    b = np.asarray(right, dtype=np.float64)
    norms = np.outer(np.linalg.norm(a, axis=1), np.linalg.norm(b, axis=1))
    dots = a @ b.T
    cosines = np.divide(dots, norms, out=np.zeros_like(dots), where=norms != 0)
    rounded: list[list[float]] = np.round(cosines, _DECIMALS).tolist()
    return rounded


def get_centroid(vectors: Sequence[Sequence[float]]) -> list[float]:
    """The mean of these vectors."""
    if not vectors:
        raise ValueError("a centroid needs at least one vector")
    centroid: list[float] = np.asarray(vectors, dtype=np.float64).mean(axis=0).tolist()
    return centroid
