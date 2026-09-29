"""Normalising job postings, and the key that deduplicates them.

The same opening turns up from several sources — a company's Greenhouse board
and its own career page carrying JSON-LD. ``canonical_key`` is what collapses
those into one posting (domain section 2.5).
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

# The longest text a posting keeps. A board can list every office an opening is
# open in as its "location"; the posting keeps the start of it rather than
# failing to store at all.
MAX_COMPANY_NAME = 255
MAX_TITLE = 512
MAX_LOCATION = 255
MAX_CANONICAL_KEY = 768
_KEY_DIGEST_CHARS = 16

_WHITESPACE = re.compile(r"\s+")
_NOISE = re.compile(r"[^a-z0-9 ]+")

# Decoration that carries no information about which job this is. Stripped so
# "Senior Backend Engineer (m/f/d)" and "Senior Backend Engineer" are one job.
_TITLE_NOISE = (
    r"\(m/f/d\)",
    r"\(m/w/d\)",
    r"\(f/m/d\)",
    r"\(all genders\)",
    r"\(remote\)",
    r"\(hybrid\)",
    r"\(onsite\)",
    r"\(full[- ]time\)",
    r"\(part[- ]time\)",
    r"\(contract\)",
    r"\(intern\)",
)
_TITLE_NOISE_RE = re.compile("|".join(_TITLE_NOISE), re.IGNORECASE)


class PostingStatus(StrEnum):
    OPEN = "open"
    EXPIRED = "expired"


class Visibility(StrEnum):
    """Crawled postings are shared; pasted JDs belong to one user."""

    SHARED = "shared"
    PRIVATE = "private"


class SourceKind(StrEnum):
    ATS_BOARD = "atsBoard"
    JSON_LD = "jsonLd"
    PUBLIC_API = "publicApi"
    PASTED = "pasted"


class SourceOrigin(StrEnum):
    """Why a source is crawled (domain decision 15) — never who asked for it."""

    BASELINE = "baseline"
    DEMAND = "demand"


def normalize(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return _WHITESPACE.sub(" ", _NOISE.sub(" ", folded.lower())).strip()


def normalize_title(title: str) -> str:
    return normalize(_TITLE_NOISE_RE.sub(" ", title))


def in_market(location: str | None, market: str) -> bool:
    """Whether a posting's location falls in a market the user chose.

    Every word of the market must appear in the location, so "Berlin" takes in
    "Berlin, Germany" and "Remote" takes in "Remote, United States". Boards
    never write a location the way a user names a market, so equal strings
    almost never happen.
    """
    wanted = set(market_words(market))
    return bool(wanted) and wanted <= set(normalize(location or "").split())


def market_words(market: str) -> tuple[str, ...]:
    """The words a location must contain to be in ``market``: lowercase ASCII
    letters and digits only, so they are safe inside a database pattern."""
    return tuple(dict.fromkeys(normalize(market).split()))


def _accent_folds() -> tuple[str, str]:
    """Each lowercase accented Latin letter and the ASCII letter ``normalize``
    turns it into, for a database to fold a location the same way."""
    accented, plain = [], []
    for code in range(0xC0, 0x250):
        char = chr(code)
        if char != char.lower():
            continue
        folded = unicodedata.normalize("NFKD", char).encode("ascii", "ignore").decode()
        if len(folded) == 1 and folded.isalpha():
            accented.append(char)
            plain.append(folded.lower())
    return "".join(accented), "".join(plain)


# ("àáâ…", "aaa…"): what SQL's translate() needs to match ``market_words``.
ACCENT_FOLDS = _accent_folds()


def clip(text: str, limit: int) -> str:
    """Text cut to at most ``limit`` characters, marked with an ellipsis when cut."""
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def canonical_key(*, company: str, title: str, location: str | None) -> str:
    """company + normalized title + location, as the domain doc specifies.

    A key longer than storage allows keeps its readable start and ends in a
    digest of the whole, so two long keys that share a start stay distinct and
    the same posting always gets the same key.
    """
    key = "|".join(
        (normalize(company), normalize_title(title), normalize(location or "unspecified"))
    )
    if len(key) <= MAX_CANONICAL_KEY:
        return key
    digest = hashlib.sha256(key.encode()).hexdigest()[:_KEY_DIGEST_CHARS]
    return f"{key[: MAX_CANONICAL_KEY - _KEY_DIGEST_CHARS - 1]}#{digest}"


@dataclass(frozen=True, slots=True)
class SalaryRange:
    min_amount: int
    max_amount: int
    currency: str

    def __post_init__(self) -> None:
        if self.min_amount > self.max_amount:
            raise ValueError("a salary range cannot start above its maximum")


@dataclass(frozen=True, slots=True)
class NormalizedPosting:
    """What every crawler adapter produces, whatever it parsed."""

    external_id: str
    company_name: str
    title: str
    location: str | None
    description: str
    url: str
    source_kind: SourceKind
    posted_on: date | None
    salary: SalaryRange | None

    def __post_init__(self) -> None:
        # Whatever a board sends, a posting holds only what storage keeps.
        object.__setattr__(self, "company_name", clip(self.company_name, MAX_COMPANY_NAME))
        object.__setattr__(self, "title", clip(self.title, MAX_TITLE))
        if self.location is not None:
            object.__setattr__(self, "location", clip(self.location, MAX_LOCATION))

    @property
    def canonical_key(self) -> str:
        return canonical_key(company=self.company_name, title=self.title, location=self.location)

    @property
    def embedding_text(self) -> str:
        """What gets embedded: title carries most of the signal, so it leads."""
        parts = [self.title, self.title, self.location or "", self.description]
        return "\n".join(part for part in parts if part).strip()


def expired_keys(seen_now: set[str], known_open: set[str]) -> set[str]:
    """Postings missing from a crawl are expired, never deleted.

    They still count toward salary-band history; they just drop out of the jobs
    list and the opening counts.
    """
    return known_open - seen_now
