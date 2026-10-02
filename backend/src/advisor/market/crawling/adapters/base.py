"""One adapter per source kind, behind an anti-corruption layer.

Each adapter takes whatever shape a board happens to return and produces
``NormalizedPosting``. Nothing downstream ever sees a vendor's field names.

The crawler may import only ``advisor.market.service`` (plus a few kernel
pieces), which is why the value objects come from there rather than from
``advisor.market.domain``.
"""

from __future__ import annotations

from typing import Any, Protocol

from advisor.market.service import NormalizedPosting, SalaryRange, SourceKind, yearly_range
from kernel.parsing import parse_date, strip_html

__all__ = ["BoardAdapter", "PostingSource", "parse_date", "salary_from", "strip_html"]


class PostingSource(Protocol):
    """Anything a crawl source's payload can be parsed by, keyed by its kind."""

    name: str
    source_kind: SourceKind

    def parse(self, payload: Any, *, company_name: str) -> list[NormalizedPosting]: ...


class BoardAdapter(PostingSource, Protocol):
    """One company's job board, found under a slug."""

    def endpoint_for(self, slug: str) -> str: ...


def salary_from(
    minimum: Any, maximum: Any, currency: Any, *, period: Any = None
) -> SalaryRange | None:
    """Only build a range when the board actually published one, as a year's
    pay: ``period`` is the board's own word for how often it is paid."""
    try:
        low = int(float(minimum))
        high = int(float(maximum)) if maximum is not None else low
    except (TypeError, ValueError):
        return None
    if low <= 0:
        return None
    code = str(currency or "").upper()[:3]
    if not code:
        return None
    return yearly_range(low, max(low, high), code, period=str(period) if period else None)
