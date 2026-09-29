"""The market's entities: what use cases load, change and save.

Plain data with the rules that belong to it. Nothing here knows how a row is
stored; ``advisor.market.infra`` maps these to and from the database.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum

from advisor.market.domain.posting import (
    MAX_COMPANY_NAME,
    MAX_LOCATION,
    MAX_TITLE,
    NormalizedPosting,
    PostingStatus,
    SalaryRange,
    SourceOrigin,
    canonical_key,
    clip,
    normalize,
)


class SourceStatus(StrEnum):
    ACTIVE = "active"
    # No longer crawled. Kept, never deleted, so the postings it found still
    # have a source that can expire them.
    RETIRED = "retired"


# --- shared zone -----------------------------------------------------------


@dataclass(slots=True)
class Company:
    id: uuid.UUID
    name: str
    # The dedup key: two spellings of one employer are one company.
    normalized_name: str
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def named(cls, name: str) -> Company:
        return cls(id=uuid.uuid4(), name=name.strip(), normalized_name=normalize(name))


@dataclass(slots=True)
class CrawlSource:
    id: uuid.UUID
    kind: str
    endpoint: str
    company_id: uuid.UUID | None
    market: str | None
    origin: SourceOrigin
    status: SourceStatus
    last_fetched_at: datetime | None = None
    last_error: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def board(
        cls, *, kind: str, endpoint: str, company_id: uuid.UUID | None, origin: SourceOrigin
    ) -> CrawlSource:
        return cls(
            id=uuid.uuid4(),
            kind=kind,
            endpoint=endpoint,
            company_id=company_id,
            market=None,
            origin=origin,
            status=SourceStatus.ACTIVE,
        )

    def record_fetch(self, at: datetime, error: str | None) -> None:
        self.last_fetched_at = at
        self.last_error = error

    def make_baseline(self, company_id: uuid.UUID) -> None:
        """A listed board is a baseline one, whoever asked for it first."""
        self.origin = SourceOrigin.BASELINE
        self.status = SourceStatus.ACTIVE
        self.company_id = self.company_id or company_id

    def retire(self) -> bool:
        """Stop crawling it. Returns whether anything changed."""
        if self.status is SourceStatus.RETIRED:
            return False
        self.status = SourceStatus.RETIRED
        return True


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
    """

    markets: tuple[str, ...]

    @property
    def includes_baseline(self) -> bool:
        return not self.markets


# --- owner zone ------------------------------------------------------------


@dataclass(slots=True)
class PrivateJobPosting:
    """A JD the user pasted. Private to them, always."""

    id: uuid.UUID
    owner_id: uuid.UUID
    canonical_key: str
    company_name: str
    title: str
    location: str | None
    description: str
    url: str | None
    # A matching crawled posting, so the user gets its weekly updates. Nothing
    # flows back the other way.
    shared_posting_id: uuid.UUID | None
    vector: list[float] | None = field(default=None)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def pasted(
        cls,
        *,
        owner_id: uuid.UUID,
        company_name: str,
        title: str,
        location: str | None,
        description: str,
        url: str | None,
        shared_posting_id: uuid.UUID | None,
    ) -> PrivateJobPosting:
        return cls(
            id=uuid.uuid4(),
            owner_id=owner_id,
            canonical_key=canonical_key(company=company_name, title=title, location=location),
            company_name=clip(company_name.strip(), MAX_COMPANY_NAME),
            title=clip(title.strip(), MAX_TITLE),
            location=clip(location, MAX_LOCATION) if location is not None else None,
            description=description,
            url=url,
            shared_posting_id=shared_posting_id,
        )


# A user works toward one to three places: a city, a country or a remote
# region (domain decision 21). The cap keeps a first role map affordable and
# the map legible.
MAX_TARGET_LOCATIONS = 3
MAX_TARGET_LOCATION = 128


class TargetLocationError(ValueError):
    """A set of target locations the market cannot scope by."""


def chosen_target_locations(values: Sequence[str]) -> tuple[str, ...]:
    """The user's target locations as they will be stored: trimmed, each
    named once (ignoring case), in the order given, and at most three."""
    chosen: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = raw.strip()
        if not value:
            raise TargetLocationError("a target location cannot be blank")
        if len(value) > MAX_TARGET_LOCATION:
            raise TargetLocationError(
                f"a target location is at most {MAX_TARGET_LOCATION} characters"
            )
        if value.casefold() in seen:
            continue
        seen.add(value.casefold())
        chosen.append(value)
    if len(chosen) > MAX_TARGET_LOCATIONS:
        raise TargetLocationError(
            f"choose at most {MAX_TARGET_LOCATIONS} target locations, got {len(chosen)}"
        )
    return tuple(chosen)


@dataclass(slots=True)
class MarketPreference:
    """One of the user's target locations (domain decision 21). The name is the
    table's, ``market_user.market_preference``, which predates the term."""

    id: uuid.UUID
    owner_id: uuid.UUID
    market: str
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def chosen(cls, *, owner_id: uuid.UUID, market: str) -> MarketPreference:
        return cls(id=uuid.uuid4(), owner_id=owner_id, market=market)
