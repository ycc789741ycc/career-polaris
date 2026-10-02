"""How well two orderings of the same roles agree.

Used to check the role map's local fit estimate, which chooses the ten roles
for free, against the fits then scored on the user's key (ADR 0027).
"""

from __future__ import annotations

from collections.abc import Sequence


def spearman(left: Sequence[float], right: Sequence[float]) -> float:
    """Spearman's rank correlation, from -1 (reversed) to 1 (the same order).
    Ties share their mean rank. 0 when either side has no spread."""
    if len(left) != len(right):
        raise ValueError("both sides need one value per item")
    if len(left) < 2:
        raise ValueError("a correlation needs at least two items")
    left_ranks, right_ranks = _ranks(left), _ranks(right)
    mean = (len(left) + 1) / 2
    covariance = sum((a - mean) * (b - mean) for a, b in zip(left_ranks, right_ranks, strict=True))
    spread = (
        sum((a - mean) ** 2 for a in left_ranks) * sum((b - mean) ** 2 for b in right_ranks)
    ) ** 0.5
    return covariance / spread if spread else 0.0


def _ranks(values: Sequence[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    start = 0
    while start < len(order):
        end = start
        while end + 1 < len(order) and values[order[end + 1]] == values[order[start]]:
            end += 1
        shared = (start + end) / 2 + 1
        for position in range(start, end + 1):
            ranks[order[position]] = shared
        start = end + 1
    return ranks
