"""Job postings: the shared openings, how they are normalised, and the key
that deduplicates them.

The same opening turns up from several sources — a company's Greenhouse board
and its own career page carrying JSON-LD. ``canonical_key`` is what collapses
those into one posting (domain section 2.5).
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from advisor.market.domain.constants import (
    MAX_CANONICAL_KEY,
    MAX_COMPANY_NAME,
    MAX_LOCATION,
    MAX_TITLE,
)

if TYPE_CHECKING:
    # Only an annotation here: source.py normalises company names with this
    # module's rules, so a runtime import would be a cycle.
    from advisor.market.domain.source import SourceKind

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


def normalize(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return _WHITESPACE.sub(" ", _NOISE.sub(" ", folded.lower())).strip()


def normalize_title(title: str) -> str:
    return normalize(_TITLE_NOISE_RE.sub(" ", title))


def names_every_word(text: str | None, phrase: str) -> bool:
    """Whether ``text`` contains every word of ``phrase``, accent-folded and in
    any order. The one word rule for a location in a market and for a posting
    matching a role the user named ("Staff Backend" takes in "Backend Engineer,
    Staff")."""
    wanted = set(market_words(phrase))
    return bool(wanted) and wanted <= set(normalize(text or "").split())


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


@dataclass(slots=True)
class JobPosting:
    """A crawled opening, shared by every user whose scope reaches it."""

    id: uuid.UUID
    canonical_key: str
    company_id: uuid.UUID
    crawl_source_id: uuid.UUID | None
    title: str
    location: str | None
    description: str
    url: str
    source_kind: str
    posted_on: date | None
    salary: SalaryRange | None
    status: PostingStatus
    first_seen_at: datetime
    last_seen_at: datetime
    # When its description and embedding were dropped because nothing held it
    # any more (ADR 0027). The row stays for Targets and salary history.
    thinned_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def first_seen(
        cls,
        posting: NormalizedPosting,
        *,
        company_id: uuid.UUID,
        source_id: uuid.UUID,
        at: datetime,
    ) -> JobPosting:
        return cls(
            id=uuid.uuid4(),
            canonical_key=posting.canonical_key,
            company_id=company_id,
            crawl_source_id=source_id,
            title=posting.title,
            location=posting.location,
            description=posting.description,
            url=posting.url,
            source_kind=str(posting.source_kind),
            posted_on=posting.posted_on,
            salary=posting.salary,
            status=PostingStatus.OPEN,
            first_seen_at=at,
            last_seen_at=at,
        )

    def seen_again(self, posting: NormalizedPosting, *, source_id: uuid.UUID, at: datetime) -> None:
        self.last_seen_at = at
        self.status = PostingStatus.OPEN
        # The same opening can arrive from several sources — a company's
        # Greenhouse board and its own career page carrying JSON-LD. Dedup
        # collapses them into one posting, and it belongs to whichever source
        # saw it last, so expiry (which is scoped per source) stays coherent
        # instead of leaving a posting that no crawl is responsible for.
        self.crawl_source_id = source_id
        self.title = posting.title
        self.description = posting.description
        self.url = posting.url
        self.thinned_at = None
        if posting.salary is not None:
            self.salary = posting.salary


@dataclass(slots=True)
class PostingEmbedding:
    """A posting's local embedding, one per posting. Platform-paid computation."""

    posting_id: uuid.UUID
    model_name: str
    vector: list[float]
    computed_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class PostingScope:
    """Which shared postings a user's role map is built from (domain decision 15).

    A posting is in scope if it is in one of their target locations. A user
    with none also gets the platform's baseline postings, so a first role map
    has something to group; with locations chosen, baseline postings in them
    are already in scope through the location match.

    A posting a search found counts only while it is on that search's current
    result list (ADR 0027): a search sees one page, so a job missing from the
    next fetch was usually pushed off it, not closed.
    """

    markets: tuple[str, ...]

    @property
    def includes_baseline(self) -> bool:
        return not self.markets
