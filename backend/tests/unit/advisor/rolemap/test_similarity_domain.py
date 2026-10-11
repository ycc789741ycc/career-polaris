"""Every cosine at once (``get_similarity_matrix``) gives what one cosine at a
time did, so moving the loops to a matrix product changes no role."""

from __future__ import annotations

import math

import pytest

from advisor.rolemap.domain.similarity import get_centroid, get_similarity_matrix


def _cosine(a: list[float], b: list[float]) -> float:
    """The loop the matrix replaced, kept here as the reference."""
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    if norm == 0:
        return 0.0
    return sum(x * y for x, y in zip(a, b, strict=True)) / norm


def test_each_cosine_is_the_one_a_loop_gives() -> None:
    # Deterministic, varied vectors the width of the embedding model's.
    left = [[math.sin(i * 7.1 + d) for d in range(384)] for i in range(6)]
    right = [[math.cos(j * 3.3 + d * 0.7) for d in range(384)] for j in range(9)]

    matrix = get_similarity_matrix(left, right)

    assert len(matrix) == 6 and all(len(row) == 9 for row in matrix)
    for i, a in enumerate(left):
        for j, b in enumerate(right):
            assert matrix[i][j] == pytest.approx(_cosine(a, b), abs=1e-9)


def test_a_zero_vector_is_like_nothing() -> None:
    assert get_similarity_matrix([[0.0, 0.0], [1.0, 0.0]], [[1.0, 0.0], [0.0, 0.0]]) == [
        [0.0, 0.0],
        [1.0, 0.0],
    ]


def test_equal_similarities_stay_equal() -> None:
    """Rounded, so a tie still goes to the better-ranked candidate."""
    [row] = get_similarity_matrix([[0.1, 0.2, 0.3]], [[1.0, 2.0, 3.0], [0.3, 0.6, 0.9]])

    assert row[0] == row[1]


def test_nothing_to_compare_is_an_empty_row_per_vector() -> None:
    assert get_similarity_matrix([], [[1.0]]) == []
    assert get_similarity_matrix([[1.0], [2.0]], []) == [[], []]


def test_vectors_of_different_lengths_are_refused() -> None:
    with pytest.raises(ValueError, match="same length"):
        get_similarity_matrix([[1.0, 2.0]], [[1.0]])


def test_a_centroid_is_the_mean_and_needs_a_vector() -> None:
    assert get_centroid([[1.0, 2.0], [3.0, 6.0]]) == [2.0, 4.0]
    with pytest.raises(ValueError, match="at least one vector"):
        get_centroid([])
