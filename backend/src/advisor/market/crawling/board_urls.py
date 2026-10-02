"""Which supported job board a URL points at, read from the URL alone.

Board discovery, which probed for a company's board when a custom role named
it, went with custom roles (Phase 8); recognising a board URL is what is left.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

# Public board URLs, by host, for the boards we have an adapter for. The slug
# is the path segment the pattern captures. Regional hosts are left out: their
# APIs live elsewhere, so the slug alone would point at the wrong board.
_BOARD_URLS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("boards.greenhouse.io", re.compile(r"^/([A-Za-z0-9_-]+)"), "greenhouse"),
    ("job-boards.greenhouse.io", re.compile(r"^/([A-Za-z0-9_-]+)"), "greenhouse"),
    ("boards-api.greenhouse.io", re.compile(r"^/v1/boards/([A-Za-z0-9_-]+)"), "greenhouse"),
    ("jobs.lever.co", re.compile(r"^/([A-Za-z0-9_-]+)"), "lever"),
    ("api.lever.co", re.compile(r"^/v0/postings/([A-Za-z0-9_-]+)"), "lever"),
    ("jobs.ashbyhq.com", re.compile(r"^/([A-Za-z0-9_.-]+)"), "ashby"),
    ("api.ashbyhq.com", re.compile(r"^/posting-api/job-board/([A-Za-z0-9_.-]+)"), "ashby"),
)


@dataclass(frozen=True, slots=True)
class BoardRef:
    adapter_name: str
    slug: str


def board_from_url(url: str) -> BoardRef | None:
    """The supported board a URL points at, read from the URL alone.

    No request is made: this only recognises the shape. ``None`` means the URL
    is not a board we know, which may still be a careers page with JSON-LD.
    """
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    if parts.scheme not in ("http", "https"):
        return None
    host = (parts.hostname or "").lower()
    for known_host, path, adapter_name in _BOARD_URLS:
        if host == known_host and (match := path.match(parts.path)):
            return BoardRef(adapter_name=adapter_name, slug=match.group(1))
    return None
