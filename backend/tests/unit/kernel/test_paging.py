"""The paging contract every repository's get_list follows."""

from __future__ import annotations

import pytest

from kernel.errors import ValidationError
from kernel.paging import Page, check_page, offset_of, paginate


@pytest.mark.parametrize(("page", "page_size"), [(1, None), (1, 1), (3, 50)])
def test_valid_pages_pass(page: int, page_size: int | None) -> None:
    check_page(page, page_size)


@pytest.mark.parametrize(("page", "page_size"), [(0, 10), (-1, None), (2, None), (1, 0)])
def test_invalid_pages_are_a_typed_error(page: int, page_size: int | None) -> None:
    with pytest.raises(ValidationError):
        check_page(page, page_size)


def test_pages_are_one_based() -> None:
    assert offset_of(1, 20) == 0
    assert offset_of(3, 20) == 40


def test_a_page_holds_its_slice_and_the_whole_count() -> None:
    page = paginate(list("abcde"), page=2, page_size=2)
    assert page == Page(items=("c", "d"), page=2, page_size=2, total=5)


def test_the_last_page_may_be_short() -> None:
    assert paginate(list("abcde"), page=3, page_size=2).items == ("e",)


def test_a_page_past_the_end_is_empty_but_still_counts() -> None:
    assert paginate(list("abc"), page=5, page_size=2) == Page((), 5, 2, 3)


def test_no_page_size_means_every_item_on_one_page() -> None:
    assert paginate(list("abc")) == Page(("a", "b", "c"), 1, None, 3)


def test_paging_in_memory_refuses_what_the_repositories_refuse() -> None:
    with pytest.raises(ValidationError):
        paginate(list("abc"), page=2, page_size=None)


def test_mapping_a_page_keeps_its_position_and_count() -> None:
    assert paginate([1, 2, 3], page=1, page_size=2).map(str) == Page(("1", "2"), 1, 2, 3)
