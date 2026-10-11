"""How the market's use cases reach stored data: interfaces in domain terms.

Every repository has the same six methods (ADR 0011, after the design
guideline's data-access rule):

* ``create`` returns the stored entity, with its timestamps.
* ``get`` returns ``None`` when nothing matches.
* ``get_list`` takes the aggregate's filter and returns one page, newest first.
  ``page`` is 1-based; ``page_size=None`` returns every match.
* ``get_count`` takes the same filter and counts every match.
* ``update`` and ``delete`` raise a not-found error when the entity is missing.

A filter field left ``None`` does not filter; set fields combine with AND. A
new question is a new filter field, not a new method. Each extra method below
says which operation the six cannot express: a bulk update, an OR query, an
insert that may already exist, or replacing a whole list.

The unit of work hands out repositories per *zone*, mirroring where the data
lives (docs/architecture.md section 3):

* ``for_owner`` — one user's owner-zone data, and nothing else of anyone's.
* ``shared`` — the shared zone: companies, sources, crawled postings.

There is no cross-user read: since ADR 0027 nothing in the market is resolved
to the users it concerns.

Each scope is one transaction. Events recorded in it are committed with it.
"""

from __future__ import annotations

import uuid
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from advisor.market.domain.events import MarketEvent
from advisor.market.domain.posting import (
    JobPosting,
    PostingEmbedding,
    PostingHead,
    PostingScope,
    PostingStatus,
)
from advisor.market.domain.search import SearchResult
from advisor.market.domain.source import Company, CrawlSource, SourceOrigin, SourceStatus
from advisor.market.domain.target_locations import MarketPreference


class Repository[Entity, Filter](Protocol):
    """The six methods, as every market repository has them."""

    async def create(self, entity: Entity) -> Entity: ...

    async def get(self, entity_id: uuid.UUID) -> Entity | None: ...

    async def get_list(
        self, filter: Filter, page: int = 1, page_size: int | None = None
    ) -> list[Entity]: ...

    async def get_count(self, filter: Filter) -> int: ...

    async def update(self, entity: Entity) -> Entity: ...

    async def delete(self, entity_id: uuid.UUID) -> None: ...


# --- shared zone -----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CompanyFilter:
    ids: tuple[uuid.UUID, ...] | None = None
    normalized_name: str | None = None


class CompanyRepository(Repository[Company, CompanyFilter], Protocol): ...


@dataclass(frozen=True, slots=True)
class CrawlSourceFilter:
    status: SourceStatus | None = None
    origin: SourceOrigin | None = None
    company_id: uuid.UUID | None = None
    kind: str | None = None
    endpoint: str | None = None
    ids: tuple[uuid.UUID, ...] | None = None
    # True: only sources a build is waiting for.
    is_due: bool | None = None
    # True: only searches of a job API; False: only company boards.
    is_search: bool | None = None
    # Sources no build has needed since this moment.
    requested_before: datetime | None = None


class CrawlSourceRepository(Repository[CrawlSource, CrawlSourceFilter], Protocol):
    async def create_if_absent(self, source: CrawlSource) -> bool:
        """Store ``source`` unless one with its kind and endpoint exists.
        Returns whether it was stored.

        Extra method: two builds may ask for the same new search at once, and
        an insert that may already exist must not fail its transaction.
        """
        ...


@dataclass(frozen=True, slots=True)
class JobPostingFilter:
    ids: tuple[uuid.UUID, ...] | None = None
    canonical_key: str | None = None
    status: PostingStatus | None = None
    # True: only postings that published pay.
    has_salary: bool | None = None
    # Postings with no embedding yet from this model.
    missing_embedding_for: str | None = None


class JobPostingRepository(Repository[JobPosting, JobPostingFilter], Protocol):
    async def expire_unseen(self, source_id: uuid.UUID, seen_keys: set[str]) -> int:
        """Mark this source's open postings that were not seen as expired, never
        deleted. Returns how many.

        Extra method: a bulk update over every posting of one source, which the
        six methods would turn into one load and one write per posting.
        """
        ...

    async def get_open_in_scope(self, scope: PostingScope) -> list[JobPosting]:
        """Open postings in a user's scope, newest first. A posting a search
        found counts only while it is on a current result list.

        Extra method: the scope is an OR (one of several target locations,
        or a baseline source), which a filter's AND cannot express.
        """
        ...

    async def get_open_heads_in_scope(
        self, scope: PostingScope, posting_ids: tuple[uuid.UUID, ...] | None = None
    ) -> list[PostingHead]:
        """``get_open_in_scope`` without descriptions, newest first; only
        ``posting_ids`` among them when given.

        Extra method: the same OR as ``get_open_in_scope``, reading only the
        columns matching and listing need, so a scope of thousands crosses
        the network without its descriptions.
        """
        ...

    async def thin_unheld(self, *, unseen_since: datetime, at: datetime) -> int:
        """Drop the description and embedding of every posting nothing holds
        (not open on a board, on no current result list) and nobody has seen
        since ``unseen_since``. Returns how many.

        Extra method: a bulk update across every source, decided by a join.
        """
        ...


@dataclass(frozen=True, slots=True)
class SearchResultFilter:
    crawl_source_ids: tuple[uuid.UUID, ...] | None = None
    job_posting_ids: tuple[uuid.UUID, ...] | None = None


class SearchResultRepository(Repository[SearchResult, SearchResultFilter], Protocol):
    async def replace(
        self, crawl_source_id: uuid.UUID, posting_ids: list[uuid.UUID], *, at: datetime
    ) -> None:
        """Make ``posting_ids``, in order, the search's whole result list.

        Extra method: a list replaced at once, which one delete and one create
        per row would leave half-written to a concurrent read.
        """
        ...


@dataclass(frozen=True, slots=True)
class PostingEmbeddingFilter:
    posting_ids: tuple[uuid.UUID, ...] | None = None
    model_name: str | None = None


class PostingEmbeddingRepository(Repository[PostingEmbedding, PostingEmbeddingFilter], Protocol):
    """Keyed by posting id: a posting has at most one embedding."""


class SharedMarket(Protocol):
    companies: CompanyRepository
    sources: CrawlSourceRepository
    postings: JobPostingRepository
    embeddings: PostingEmbeddingRepository
    search_results: SearchResultRepository

    def record(self, event: MarketEvent) -> None: ...


# --- owner zone ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MarketPreferenceFilter:
    market: str | None = None


class MarketPreferenceRepository(
    Repository[MarketPreference, MarketPreferenceFilter], Protocol
): ...


class OwnerMarket(Protocol):
    markets: MarketPreferenceRepository

    def record(self, event: MarketEvent) -> None: ...


# --- unit of work ----------------------------------------------------------


class MarketUnitOfWork(Protocol):
    def for_owner(self, owner_id: uuid.UUID) -> AbstractAsyncContextManager[OwnerMarket]: ...

    def shared(self) -> AbstractAsyncContextManager[SharedMarket]: ...
