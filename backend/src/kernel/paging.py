"""The paging contract every repository's ``get_list`` follows.

``page`` is 1-based. ``page_size=None`` returns every match, and then ``page``
must be 1. Anything else is a caller mistake, reported as a typed error rather
than an empty page.

A list use case returns a ``Page``: the items asked for and how many there are
in all (ADR 0014).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from kernel.errors import ValidationError


def check_page(page: int, page_size: int | None) -> None:
    if page < 1:
        raise ValidationError("page starts at 1", page=page)
    if page_size is None:
        if page != 1:
            raise ValidationError("an unpaged list has only page 1", page=page)
        return
    if page_size < 1:
        raise ValidationError("page_size must be at least 1", page_size=page_size)


def offset_of(page: int, page_size: int) -> int:
    return (page - 1) * page_size


@dataclass(frozen=True, slots=True)
class Page[T]:
    """One page of a list, and how many items the whole list holds.

    ``page_size`` is ``None`` when the caller asked for everything; then there
    is exactly one page and ``total`` is ``len(items)``.
    """

    items: tuple[T, ...]
    page: int
    page_size: int | None
    total: int

    def map[U](self, convert: Callable[[T], U]) -> Page[U]:
        return Page(tuple(convert(i) for i in self.items), self.page, self.page_size, self.total)


def paginate[T](items: Sequence[T], page: int = 1, page_size: int | None = None) -> Page[T]:
    """Page a list already in memory.

    For lists a use case builds after reading — deduplicated, re-sorted or
    merged from several sources — where paging in SQL would page the wrong
    rows. A page past the end is empty, not an error: ``total`` says why.
    """
    check_page(page, page_size)
    if page_size is None:
        return Page(tuple(items), 1, None, len(items))
    start = offset_of(page, page_size)
    return Page(tuple(items[start : start + page_size]), page, page_size, len(items))
