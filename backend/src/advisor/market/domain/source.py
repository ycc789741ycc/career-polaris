"""Where postings come from: the companies, and the boards and searches that
are fetched for them only when a build asks (ADR 0027).

Plain data with the rules that belong to it; ``advisor.market.infra`` maps
these to and from the database.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from advisor.market.domain.posting import normalize


class SourceKind(StrEnum):
    ATS_BOARD = "atsBoard"
    JSON_LD = "jsonLd"
    PUBLIC_API = "publicApi"
    PASTED = "pasted"


class SourceOrigin(StrEnum):
    """Why a source is crawled (domain decision 15) — never who asked for it."""

    BASELINE = "baseline"
    DEMAND = "demand"


class SourceStatus(StrEnum):
    ACTIVE = "active"
    # No longer fetched. Kept, never deleted, so the postings it found still
    # have a source that says where they came from.
    RETIRED = "retired"


@dataclass(frozen=True, slots=True)
class FreshWindows:
    """How long a fetch is reused before a build asks for it again (ADR 0027).

    A search is a request to one shared, rate-limited API, so it is reused
    longer than a board, which is one cheap request listing everything.
    """

    search: timedelta
    board: timedelta


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
    # When a build last needed it. Never who.
    last_requested_at: datetime | None = None
    # Set while a build waits for it to be fetched; cleared once it has been.
    due_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def search(cls, *, kind: str, endpoint: str, market: str, at: datetime) -> CrawlSource:
        """A search of a public job API for one job title in one place (ADR
        0025): a ``demand`` source with no company and no owner, filed under
        the place it searches."""
        return cls(
            id=uuid.uuid4(),
            kind=kind,
            endpoint=endpoint,
            company_id=None,
            market=market,
            origin=SourceOrigin.DEMAND,
            status=SourceStatus.ACTIVE,
            last_requested_at=at,
        )

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

    def fetched(self) -> None:
        """Its fetch is stored and embedded: no build waits for it any more."""
        self.due_at = None

    @property
    def is_due(self) -> bool:
        return self.due_at is not None

    def is_fresh(self, at: datetime, windows: FreshWindows) -> bool:
        """Fetched recently enough to be reused, by its own window."""
        if self.last_fetched_at is None:
            return False
        window = windows.search if self.is_search else windows.board
        return at - self.last_fetched_at <= window

    def needed(self, at: datetime, windows: FreshWindows) -> bool:
        """A build needs this source. It is marked asked for, and due when it
        isn't fresh. Returns whether that build has to wait for it.

        A retired search is fetched afresh; marking is idempotent, so two
        builds that need the same stale source wait on one fetch.
        """
        self.last_requested_at = at
        if self.status is SourceStatus.RETIRED:
            self.status = SourceStatus.ACTIVE
            self.last_fetched_at = None
        if self.due_at is None and not self.is_fresh(at, windows):
            self.due_at = at
        return self.due_at is not None

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

    @property
    def is_search(self) -> bool:
        """A search of a job API is filed under the place it searches; a
        company's board has no place."""
        return self.market is not None

    def retire_idle(self) -> bool:
        """Retire a search no build has needed in a while. Returns whether it
        was one to retire."""
        if not self.is_search:
            return False
        self.due_at = None
        return self.retire()
