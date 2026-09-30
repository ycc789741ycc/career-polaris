from advisor.market.crawling.adapters.ashby import AshbyAdapter
from advisor.market.crawling.adapters.base import (
    BoardAdapter,
    PostingSource,
    parse_date,
    salary_from,
    strip_html,
)
from advisor.market.crawling.adapters.greenhouse import GreenhouseAdapter
from advisor.market.crawling.adapters.himalayas import HimalayasAdapter
from advisor.market.crawling.adapters.json_ld import JsonLdAdapter
from advisor.market.crawling.adapters.lever import LeverAdapter

# Probed in order when discovering a board for a newly named company.
ATS_ADAPTERS: tuple[BoardAdapter, ...] = (
    GreenhouseAdapter(),
    LeverAdapter(),
    AshbyAdapter(),
)

BY_NAME: dict[str, BoardAdapter] = {
    adapter.name: adapter for adapter in (*ATS_ADAPTERS, JsonLdAdapter())
}

# Public job APIs searched by title and place rather than read per company
# (ADR 0025). Never probed by discovery: they are not a company's board.
SEARCH_ADAPTERS: tuple[HimalayasAdapter, ...] = (HimalayasAdapter(),)

# Every kind a crawl source can have, and what parses its payload.
SOURCES: dict[str, PostingSource] = {
    **BY_NAME,
    **{adapter.name: adapter for adapter in SEARCH_ADAPTERS},
}

__all__ = [
    "ATS_ADAPTERS",
    "BY_NAME",
    "SEARCH_ADAPTERS",
    "SOURCES",
    "AshbyAdapter",
    "BoardAdapter",
    "GreenhouseAdapter",
    "HimalayasAdapter",
    "JsonLdAdapter",
    "LeverAdapter",
    "PostingSource",
    "parse_date",
    "salary_from",
    "strip_html",
]
